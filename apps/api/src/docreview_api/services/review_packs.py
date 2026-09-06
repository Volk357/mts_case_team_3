"""Tenant-scoped and filesystem-safe Review Pack catalog."""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from uuid import UUID

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


class ReviewPackCatalogService:
    """Expose only active pack references resolvable inside the configured root."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        review_packs_root: Path,
    ) -> None:
        self._session_factory = session_factory
        self._review_packs_root = review_packs_root.resolve()

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
