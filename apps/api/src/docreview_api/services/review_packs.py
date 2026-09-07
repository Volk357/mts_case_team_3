"""Tenant-scoped and filesystem-safe Review Pack catalog."""

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from uuid import UUID, uuid4

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from docreview_api.db.models import ReviewPackReferenceModel

# Файлы настройки пакета и то, что каждый из них задаёт.
#
# Зачем это в API. Главное продуктовое утверждение — «под другую компанию
# перенастраивается конфигурацией, а не кодом». До сих пор оно жило только
# в презентации, и проверить его пользователь не мог. Теперь состав активного
# пакета читается из его манифеста и показывается в интерфейсе.
#
# ОПИСАНИЯ заданы здесь, а не берутся из манифеста: манифест лежит на диске,
# и его содержимое — не доверенный источник текста для показа пользователю.
#
# ИМЕНА повторяют то, как файлы резолвит ЯДРО (`docreview.resolve_pack`),
# и это повторение обязано быть точным: блок отвечает на вопрос «какие файлы
# применяются», и любое расхождение делает ответ ложным.
#
# Как именно резолвит ядро (проверено по коду):
#   * template, defects, glossary — ВСЕГДА фиксированные имена, манифест
#     на них не влияет;
#   * policy — имя из `contents.policy`, если оно там объявлено, иначе
#     `policy.yaml` по соглашению.
#
# Поэтому имя из манифеста берётся только для policy. Показать манифестное
# имя для остальных трёх значило бы объявить применяемым файл, который ядро
# проигнорирует. Найдено на ревью.
PACK_CONTENT_ROLES: tuple[tuple[str, str, str], ...] = (
    (
        "template",
        "template.yaml",
        "Структура документа: какие разделы обязательны и что в них проверяется",
    ),
    ("defects", "defects.yaml", "Таксономия дефектов и конвенции компании — что считать ошибкой"),
    ("glossary", "glossary.yaml", "Термины, которые в компании не расшифровывают"),
    (
        "policy",
        "policy.yaml",
        "Политика приёмки: сколько замечаний показывать и что дороже — пропуск или шум",
    ),
)


class InvalidDeclaration:
    """Манифест объявляет файл политики, но объявление негодно.

    Отдельный тип, а не `object()`: так проверка типов сужает результат
    и не даёт передать часового туда, где ожидается имя файла.
    """


# Ядро такой пакет отвергает целиком, и состав показывать нельзя.
INVALID_DECLARATION = InvalidDeclaration()

# Имена манифеста — те же, что перебирает ядро.
PACK_MANIFEST_NAMES: tuple[str, ...] = ("pack.yaml", "pack.yml", "manifest.yaml", "manifest.yml")


@dataclass(frozen=True, slots=True)
class ReviewPackContent:
    """Один файл настройки пакета."""

    key: str
    filename: str
    description: str
    present: bool


# Склонность приёмки, которую пакет объявляет в policy.yaml. Наружу
# выпускается закрытый перечень: значение из файла на диске — не то, что
# стоит показывать пользователю без проверки.
PACK_BIASES: frozenset[str] = frozenset({"recall", "precision", "balanced"})


@dataclass(frozen=True, slots=True)
class ReviewPackSnapshot:
    id: UUID
    display_name: str
    document_type: str
    version: str
    contents: tuple[ReviewPackContent, ...] = ()
    # Склонность приёмки профиля: по ней человек выбирает между «покажи
    # больше» и «покажи только уверенное». None — пакет её не объявляет.
    policy_bias: str | None = None


# Версия пакета — часть контракта: приложение сверяет id и version
# из результата ядра с заданием и бракует результат при расхождении.
# Поэтому в имени версии допускаем только то, что безопасно и как имя
# каталога, и как значение в манифесте.
VERSION_PATTERN = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,49}$")

# Сколько ждём проверку пакета ядром. Здоровый пакет проверяется за
# ~150 мс; секунды означают регулярку с катастрофическим возвратом,
# и ядро само отвергнет такой пакет по своему бюджету.
VALIDATION_TIMEOUT_SECONDS = 60.0


class ReviewPackEditError(ValueError):
    """Правка пакета отклонена. Несёт код для ответа API."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PackSource:
    """Тексты файлов пакета для правки."""

    pack_key: str
    version: str
    display_name: str
    files: dict[str, str]


class ReviewPackCatalogService:
    """Expose only active pack references resolvable inside the configured root."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        review_packs_root: Path,
        analysis_executable: str = "docreview",
    ) -> None:
        self._session_factory = session_factory
        self._review_packs_root = review_packs_root.resolve()
        # Проверку правки делает ЯДРО той же командой, что доступна воркеру.
        # Своей валидации у приложения нет и быть не должно: второй валидатор
        # разъедется с первым, и пакет, принятый интерфейсом, будет отвергнут
        # анализом. Ровно этой ценой уже платили за состав пакета в UI.
        self._analysis_executable = analysis_executable

    def list_available(self, *, company_id: UUID) -> tuple[ReviewPackSnapshot, ...]:
        with self._session_factory() as session:
            records = session.scalars(
                select(ReviewPackReferenceModel)
                .where(
                    ReviewPackReferenceModel.company_id == company_id,
                    ReviewPackReferenceModel.is_active.is_(True),
                )
                .order_by(
                    ReviewPackReferenceModel.display_name,
                    ReviewPackReferenceModel.version,
                    ReviewPackReferenceModel.id,
                )
            ).all()
            return tuple(
                snapshot
                for record in records
                if (snapshot := self._public_snapshot(record)) is not None
            )

    def _public_snapshot(self, record: ReviewPackReferenceModel) -> ReviewPackSnapshot | None:
        display_name = record.display_name.strip()
        document_type = record.document_type.strip()
        version = record.version.strip()
        if not display_name or not document_type or not version:
            return None
        resolved = self._resolve_locator(record.locator)
        if resolved is None:
            return None
        contents = self._contents(resolved)
        return ReviewPackSnapshot(
            id=record.id,
            display_name=display_name,
            document_type=document_type,
            version=version,
            contents=contents,
            policy_bias=self._policy_bias(resolved, contents),
        )

    def _policy_bias(self, resolved: Path, contents: tuple[ReviewPackContent, ...]) -> str | None:
        """Склонность приёмки из policy.yaml пакета.

        Имя файла берётся из уже вычисленного состава, чтобы не резолвить
        манифест второй раз и не разъехаться с ним. Файла нет или он не
        объявляет склонность — None, интерфейс тогда ничего не подписывает.
        """
        policy = next((part for part in contents if part.key == "policy"), None)
        if policy is None or not policy.present:
            return None
        base = resolved.parent if resolved.is_file() else resolved
        try:
            with (base / policy.filename).open(encoding="utf-8") as handle:
                document = yaml.safe_load(handle)
        except (OSError, ValueError, yaml.YAMLError):
            return None
        if not isinstance(document, dict):
            return None
        bias = document.get("bias")
        return bias if isinstance(bias, str) and bias in PACK_BIASES else None

    def _contents(self, resolved: Path) -> tuple[ReviewPackContent, ...]:
        """Файлы настройки пакета: как они названы и лежат ли в нём на самом деле.

        Имя берётся из манифеста, если он его объявляет, иначе — по соглашению.
        Это ровно то, как файлы резолвит ядро, и расходиться нельзя: иначе
        интерфейс сообщил бы «файл не задан» про пакет, где он задан.

        Ошибка доступа или разбора — не повод ронять каталог пакетов: тогда
        работает соглашение об именах.
        """
        # Локатор может указывать на сам манифест — тогда каталогом пакета
        # служит его родитель, а манифестом именно этот файл. Ядро делает
        # так же; искать `pack.yaml` рядом было бы неверно.
        base: Path
        manifest: Path | None
        if resolved.is_file():
            base, manifest = resolved.parent, resolved
        else:
            base = resolved
            manifest = next(
                (candidate for name in PACK_MANIFEST_NAMES if (candidate := base / name).is_file()),
                None,
            )

        policy_name = self._declared_policy_name(manifest)
        if isinstance(policy_name, InvalidDeclaration):
            # Ядро отвергает такой пакет целиком (ReviewPackInvalid), проверка
            # по нему не запустится. Показывать состав, как будто он рабочий, —
            # значит обещать то, чего не будет.
            return ()
        # Проверка файла политики — ПОСЛЕ обеих веток, а не внутри ветки
        # объявленного имени. Ядро делает так же (docreview.py), и ровно эта
        # ошибка была найдена в нём сегодня же: симлинк `policy.yaml -> ../..`
        # проходил проверку имени и `is_file()`, а политика читалась снаружи
        # пакета. Повторять её здесь нельзя.
        #
        # Разница между ветками только в том, чем оборачивается ОТСУТСТВИЕ
        # файла: объявленный в манифесте обязан существовать (иначе ядро
        # отвергает пакет), а файл по соглашению существовать не обязан —
        # тогда работают умолчания ядра.
        policy_file = policy_name or "policy.yaml"
        policy_exists = (base / policy_file).is_file()
        if policy_name is not None and not policy_exists:
            return ()
        if policy_exists and not self._inside_pack(base, policy_file):
            return ()

        items: list[ReviewPackContent] = []
        for key, default_name, description in PACK_CONTENT_ROLES:
            filename = policy_name if key == "policy" and policy_name else default_name
            try:
                present = (base / filename).is_file()
            except OSError:
                present = False
            items.append(
                ReviewPackContent(
                    key=key,
                    filename=filename,
                    description=description,
                    present=present,
                )
            )
        return tuple(items)

    @staticmethod
    def _inside_pack(base: Path, filename: str) -> bool:
        """Разрешённый путь файла лежит внутри пакета.

        Проверка realpath, а не только `is_file()`: симлинк наружу проходит
        `is_file()`, но ядро такой пакет отвергает — политика читалась бы
        из неверсионируемого места.
        """
        try:
            return (base / filename).resolve().is_relative_to(base.resolve())
        except OSError:
            return False

    @staticmethod
    def _declared_policy_name(manifest: Path | None) -> str | InvalidDeclaration | None:
        """Имя файла политики из манифеста, как его читает ядро.

        Три исхода, а не два:
          * имя — объявлено и пригодно;
          * None — не объявлено, действует соглашение `policy.yaml`;
          * INVALID_DECLARATION — объявлено, но негодно, и тогда ядро
            отвергает пакет целиком (`ReviewPackInvalid`).

        Схлопывать последние два нельзя: «не объявлено» означает рабочий
        пакет на умолчаниях, «объявлено сломанно» — пакет, который вообще
        не запустится. Показать их одинаково значило бы обещать проверку,
        которой не будет.
        """
        if manifest is None:
            return None
        try:
            with manifest.open(encoding="utf-8") as handle:
                document = yaml.safe_load(handle)
        except (OSError, ValueError, yaml.YAMLError):
            # ValueError покрывает UnicodeDecodeError: манифест в чужой
            # кодировке иначе ронял ВЕСЬ каталог пакетов пятисоткой, а с ним
            # и главный экран. Ядро такой пакет просто отвергает.
            return INVALID_DECLARATION
        if not isinstance(document, dict):
            # Пустой манифест (None) сюда тоже попадает: ядро объявляет
            # манифест источником истины и требует от него полноты.
            return INVALID_DECLARATION
        # Манифест есть — он ОБЯЗАН объявлять идентичность. Ядро без неё
        # отвергает пакет («манифест не объявляет: id/pack_key, version»),
        # то есть проверка по такому пакету не запустится вовсе.
        if not (document.get("id") or document.get("pack_key")) or not document.get("version"):
            return INVALID_DECLARATION
        # Ядро различает «ключа нет» и «ключ есть со значением null»:
        # первое — соглашение, второе — сломанный манифест, пакет отвергается.
        if "contents" not in document:
            return None
        contents = document["contents"]
        if not isinstance(contents, dict):
            return INVALID_DECLARATION
        if "policy" not in contents:
            return None

        value = contents["policy"]
        if not isinstance(value, str) or not value.strip():
            return INVALID_DECLARATION
        filename = value.strip()
        if (
            "/" in filename
            or "\\" in filename
            or filename in {".", ".."}
            or PurePosixPath(filename).is_absolute()
            or PureWindowsPath(filename).is_absolute()
        ):
            return INVALID_DECLARATION
        return filename

    def read_source(self, *, company_id: UUID, pack_id: UUID) -> PackSource:
        """Тексты настраиваемых файлов пакета — то, что правит человек.

        Возвращаются только файлы, которые ЯДРО действительно применяет:
        имена берутся из той же таблицы ролей, что и блок состава пакета.
        Показать здесь файл, который ядро проигнорирует, значило бы дать
        править то, что ни на что не влияет.
        """
        record, resolved = self._editable_record(company_id, pack_id)
        files: dict[str, str] = {}
        for content in self._contents(resolved):
            if not content.present:
                continue
            path = resolved / content.filename
            try:
                files[content.key] = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as error:
                raise ReviewPackEditError(
                    "REVIEW_PACK_FILE_UNREADABLE",
                    f"файл {content.filename} не читается: {error}",
                ) from error
        return PackSource(
            pack_key=record.pack_key,
            version=record.version,
            display_name=record.display_name,
            files=files,
        )

    def create_version(
        self,
        *,
        company_id: UUID,
        pack_id: UUID,
        version: str,
        files: dict[str, str],
    ) -> UUID:
        """Выпустить НОВУЮ версию пакета с изменёнными файлами.

        Опубликованная версия неизменяема. Иначе рассыпается всё, на чём
        держится доказательность: прошлые проверки ссылаются на версию,
        замеры полноты сняты на конкретной версии, а результат ядра
        сверяется с заданием по id и version.

        Порядок намеренно такой: собрать во временном каталоге → отдать
        ядру на проверку → и только потом перенести в каталог пакетов и
        зарегистрировать. При отказе на диске не остаётся ни каталога,
        ни записи, на которую сослались бы задания.
        """
        if not VERSION_PATTERN.match(version or ""):
            raise ReviewPackEditError(
                "REVIEW_PACK_VERSION_INVALID",
                "версия может содержать буквы, цифры, точку, дефис и подчёркивание, до 50 символов",
            )

        record, source_dir = self._editable_record(company_id, pack_id)
        known = {key for key, _filename, _description in PACK_CONTENT_ROLES}
        unknown = sorted(set(files) - known)
        if unknown:
            raise ReviewPackEditError(
                "REVIEW_PACK_FILE_UNKNOWN",
                "неизвестные файлы: {}".format(", ".join(unknown)),
            )

        target = (self._review_packs_root / record.pack_key / version).resolve()
        if not self._is_inside_root(target):
            raise ReviewPackEditError(
                "REVIEW_PACK_VERSION_INVALID",
                "версия уводит за пределы каталога пакетов",
            )
        if target.exists():
            raise ReviewPackEditError(
                "REVIEW_PACK_VERSION_EXISTS",
                f"версия {version} уже существует и не может быть изменена",
            )
        if self._version_registered(company_id, record.pack_key, version):
            raise ReviewPackEditError(
                "REVIEW_PACK_VERSION_EXISTS",
                f"версия {version} уже зарегистрирована",
            )

        staging = Path(tempfile.mkdtemp(prefix="pack-"))
        try:
            draft = staging / "pack"
            shutil.copytree(source_dir, draft)
            self._write_files(draft, files)
            # Манифест — источник истины по версии для ядра. Если оставить
            # в нём прежнее значение, ядро вернёт старую версию, приложение
            # сверит её с заданием и забракует результат целиком.
            self._rewrite_manifest_version(draft, version)
            self._validate_with_core(draft)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(draft), str(target))
        finally:
            shutil.rmtree(staging, ignore_errors=True)

        locator = f"{record.pack_key}/{version}"
        new_id = uuid4()
        now = datetime.now(UTC)
        with self._session_factory.begin() as session:
            session.add(
                ReviewPackReferenceModel(
                    id=new_id,
                    company_id=company_id,
                    pack_key=record.pack_key,
                    version=version,
                    display_name=record.display_name,
                    document_type=record.document_type,
                    locator=locator,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
            )
        return new_id

    def _editable_record(
        self, company_id: UUID, pack_id: UUID
    ) -> tuple[ReviewPackReferenceModel, Path]:
        with self._session_factory() as session:
            record = session.scalars(
                select(ReviewPackReferenceModel).where(
                    ReviewPackReferenceModel.id == pack_id,
                    ReviewPackReferenceModel.company_id == company_id,
                    ReviewPackReferenceModel.is_active.is_(True),
                )
            ).one_or_none()
            if record is None:
                raise ReviewPackEditError("REVIEW_PACK_NOT_FOUND", "профиль проверки не найден")
            resolved = self._resolve_locator(record.locator)
            if resolved is None:
                raise ReviewPackEditError(
                    "REVIEW_PACK_NOT_FOUND",
                    "каталог профиля недоступен",
                )
            session.expunge(record)
            return record, resolved

    def _version_registered(self, company_id: UUID, pack_key: str, version: str) -> bool:
        with self._session_factory() as session:
            return (
                session.scalars(
                    select(ReviewPackReferenceModel).where(
                        ReviewPackReferenceModel.company_id == company_id,
                        ReviewPackReferenceModel.pack_key == pack_key,
                        ReviewPackReferenceModel.version == version,
                    )
                ).first()
                is not None
            )

    def _write_files(self, draft: Path, files: dict[str, str]) -> None:
        by_key = {key: filename for key, filename, _description in PACK_CONTENT_ROLES}
        # Имя policy может быть переопределено манифестом — берём то же
        # имя, что резолвит ядро, иначе правка легла бы в файл, который
        # никто не читает.
        declared = self._declared_policy_name(self._manifest_path(draft))
        if isinstance(declared, str):
            by_key["policy"] = declared
        for key, text in files.items():
            filename = by_key[key]
            if not self._inside_pack(draft, filename):
                raise ReviewPackEditError(
                    "REVIEW_PACK_FILE_UNKNOWN",
                    f"имя файла {filename} уводит за пределы пакета",
                )
            (draft / filename).write_text(text, encoding="utf-8")

    @staticmethod
    def _manifest_path(pack_dir: Path) -> Path | None:
        for name in ("pack.yaml", "pack.yml", "manifest.yaml", "manifest.yml"):
            candidate = pack_dir / name
            if candidate.is_file():
                return candidate
        return None

    def _rewrite_manifest_version(self, draft: Path, version: str) -> None:
        manifest = self._manifest_path(draft)
        if manifest is None:
            return
        try:
            data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise ReviewPackEditError(
                "REVIEW_PACK_INVALID", f"манифест не читается: {error}"
            ) from error
        if not isinstance(data, dict):
            raise ReviewPackEditError("REVIEW_PACK_INVALID", "манифест не является словарём")
        data["version"] = version
        manifest.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def _validate_with_core(self, draft: Path) -> None:
        """Проверка ядром. Своей валидации приложение не имеет намеренно."""
        report = draft.parent / "validation.json"
        try:
            completed = subprocess.run(
                [
                    self._analysis_executable,
                    "validate-pack",
                    "--pack",
                    str(draft),
                    "--output",
                    str(report),
                ],
                capture_output=True,
                timeout=VALIDATION_TIMEOUT_SECONDS,
                check=False,
                # Окружение не наследуем: конфигурация модели и секреты
                # проверке пакета не нужны.
                env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"},
            )
        except FileNotFoundError as error:
            raise ReviewPackEditError(
                "REVIEW_PACK_VALIDATOR_UNAVAILABLE",
                "проверяющая команда ядра недоступна",
            ) from error
        except subprocess.TimeoutExpired as error:
            raise ReviewPackEditError(
                "REVIEW_PACK_VALIDATION_TIMEOUT",
                "проверка пакета не уложилась в отведённое время",
            ) from error

        try:
            payload = json.loads(report.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ReviewPackEditError(
                "REVIEW_PACK_VALIDATOR_UNAVAILABLE",
                f"проверяющая команда ядра не вернула отчёт (код {completed.returncode})",
            ) from error

        if not payload.get("ok"):
            error_payload = payload.get("error") or {}
            raise ReviewPackEditError(
                str(error_payload.get("code") or "REVIEW_PACK_INVALID"),
                str(error_payload.get("message") or "пакет не прошёл проверку"),
            )

    def _is_inside_root(self, candidate: Path) -> bool:
        try:
            candidate.relative_to(self._review_packs_root)
        except ValueError:
            return False
        return True

    def _resolve_locator(self, locator: str) -> Path | None:
        posix = PurePosixPath(locator)
        if (
            not locator
            or locator == "."
            or posix.is_absolute()
            or PureWindowsPath(locator).is_absolute()
            or "\\" in locator
            or ".." in posix.parts
        ):
            return None
        try:
            candidate = self._review_packs_root.joinpath(*posix.parts).resolve()
            if not candidate.is_relative_to(self._review_packs_root):
                return None
            if candidate.is_file():
                return (
                    candidate if candidate.suffix.casefold() in {".yaml", ".yml", ".json"} else None
                )
            if candidate.is_dir() and any(candidate.iterdir()):
                return candidate
        except OSError:
            return None
        return None
