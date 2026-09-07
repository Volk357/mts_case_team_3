"""Правка Review Pack через API: чтение исходников и выпуск новой версии.

Почему эти эндпоинты вообще есть. Главное продуктовое утверждение —
«под другую организацию перенастраивается конфигурацией, а не кодом».
До сих пор конфигурацию можно было только посмотреть; менять её приходилось
по ssh. Теперь её правит человек, и появляется два новых риска, ради которых
и написаны эти тесты.

Первый: **опубликованная версия неизменяема**. Результаты прошлых проверок
ссылаются на версию пакета, замеры полноты сняты на конкретной версии,
а ядро возвращает id и version в результате, и приложение сверяет их
с заданием. Правка «на месте» разрушила бы всё это разом, поэтому правка
обязана порождать новую версию.

Второй: **пакет проверяет ядро, а не приложение**. Второй валидатор
неминуемо разъедется с первым, и пакет, принятый интерфейсом, будет
отвергнут анализом.
"""

import shutil
import stat
import sys
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from docreview_api.config import Settings
from docreview_api.db.base import Base
from docreview_api.db.models import CompanyModel, ReviewPackReferenceModel
from docreview_api.db.session import create_database_engine, create_session_factory
from docreview_api.main import create_app
from docreview_api.services.review_packs import ReviewPackCatalogService

REPOSITORY = Path(__file__).resolve().parents[3]
REAL_PACK = REPOSITORY / "review-packs" / "mts-net" / "0.2"


def _core_shim(tmp_path: Path) -> str:
    """Исполняемая обёртка над ядром — то же, что на сервере.

    Проверка обязана идти через настоящий CLI: тест, вызывающий функцию
    напрямую, доказал бы работу механизма в обход того пути, которым
    пользуется приложение.
    """
    shim = tmp_path / "docreview-shim"
    shim.write_text(
        '#!/bin/sh\nexec {python} {core} "$@"\n'.format(
            python=sys.executable, core=REPOSITORY / "docreview.py"
        ),
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(shim)


@pytest.fixture
def authoring(tmp_path: Path, database_url: str) -> Iterator[tuple[Settings, UUID]]:
    """Каталог с копией настоящего пакета: его и правим."""
    packs_root = tmp_path / "review-packs"
    shutil.copytree(REAL_PACK, packs_root / "mts-net" / "0.2")

    settings = Settings(
        environment="test",
        database_url=database_url,
        review_packs_dir=packs_root,
        analysis_executable=_core_shim(tmp_path),
        _env_file=None,
    )
    engine = create_database_engine(settings.database_url)
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        session.add(
            CompanyModel(
                id=settings.default_company_id,
                slug=settings.default_company_slug,
                display_name=settings.default_company_name,
            )
        )
        session.flush()
        record = ReviewPackReferenceModel(
            company_id=settings.default_company_id,
            pack_key="mts-net",
            version="0.2",
            display_name="Потоковые данные и витрины (МТС NET)",
            document_type="technical_specification",
            locator="mts-net/0.2",
        )
        session.add(record)
        session.flush()
        pack_id = record.id
    try:
        yield settings, pack_id
    finally:
        # Открытое соединение не даёт удалить базу теста, и уборка фикстуры
        # падает на соседнем тесте — плавающая ошибка, которую дорого искать.
        engine.dispose()


def client(settings: Settings) -> AsyncClient:
    app = create_app(settings)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.anyio
async def test_source_returns_files_the_core_actually_applies(authoring):
    settings, pack_id = authoring
    async with client(settings) as http:
        response = await http.get(f"/api/review-packs/{pack_id}/source")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pack_key"] == "mts-net"
    assert body["version"] == "0.2"
    # Ровно те файлы, которые применяет ядро, и с настоящим содержимым.
    assert set(body["files"]) == {"template", "defects", "glossary", "policy"}
    assert "sections:" in body["files"]["template"]
    assert "defects:" in body["files"]["defects"]


@pytest.mark.anyio
async def test_new_version_is_created_validated_and_listed(authoring):
    settings, pack_id = authoring
    async with client(settings) as http:
        source = (await http.get(f"/api/review-packs/{pack_id}/source")).json()
        policy = source["files"]["policy"].replace("ceiling: 20", "ceiling: 12", 1)
        created = await http.post(
            f"/api/review-packs/{pack_id}/versions",
            json={"version": "0.2.1", "files": {"policy": policy}},
        )
        assert created.status_code == 201, created.text
        catalog = (await http.get("/api/review-packs")).json()

    assert created.json()["version"] == "0.2.1"
    versions = {item["version"] for item in catalog["items"]}
    # Новая версия появилась, СТАРАЯ ОСТАЛАСЬ: на неё ссылаются прошлые проверки.
    assert versions == {"0.2", "0.2.1"}

    published = settings.review_packs_dir / "mts-net" / "0.2.1"
    assert (published / "policy.yaml").read_text(encoding="utf-8").count("ceiling: 12")
    # Файлы, которых не касались, перенесены целиком.
    assert (published / "defects.yaml").exists()
    assert (published / "template.yaml").exists()


@pytest.mark.anyio
async def test_manifest_version_is_rewritten(authoring):
    """Без этого приложение забракует любой результат новой версии.

    Ядро берёт id и version из манифеста ВНУТРИ пакета, а приложение
    сверяет их с заданием. Если оставить в манифесте прежнее значение,
    анализ вернёт 0.2 вместо 0.2.1, и результат будет отвергнут целиком —
    при успешном завершении анализа.
    """
    settings, pack_id = authoring
    async with client(settings) as http:
        source = (await http.get(f"/api/review-packs/{pack_id}/source")).json()
        response = await http.post(
            f"/api/review-packs/{pack_id}/versions",
            json={"version": "0.9", "files": {"policy": source["files"]["policy"]}},
        )
    assert response.status_code == 201, response.text
    manifest = yaml.safe_load(
        (settings.review_packs_dir / "mts-net" / "0.9" / "pack.yaml").read_text(encoding="utf-8")
    )
    assert manifest["version"] == "0.9"
    assert manifest["id"] == "mts-net"
    # Исходная версия не тронута.
    original = yaml.safe_load(
        (settings.review_packs_dir / "mts-net" / "0.2" / "pack.yaml").read_text(encoding="utf-8")
    )
    assert original["version"] == "0.2"


@pytest.mark.anyio
async def test_existing_version_cannot_be_overwritten(authoring):
    settings, pack_id = authoring
    async with client(settings) as http:
        source = (await http.get(f"/api/review-packs/{pack_id}/source")).json()
        response = await http.post(
            f"/api/review-packs/{pack_id}/versions",
            json={"version": "0.2", "files": {"policy": source["files"]["policy"]}},
        )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REVIEW_PACK_VERSION_EXISTS"


@pytest.mark.anyio
async def test_broken_regex_is_rejected_by_the_core(authoring):
    """Правка с невалидной регуляркой не должна доходить до каталога.

    Регулярки шаблона компилируются внутри проверок, а не при загрузке
    конфига: без прогона слоя правил такой пакет прошёл бы и упал уже
    на документе заказчика.
    """
    settings, pack_id = authoring
    async with client(settings) as http:
        source = (await http.get(f"/api/review-packs/{pack_id}/source")).json()
        broken = source["files"]["template"].replace(
            "trigger: '\\bHDFS\\b'", "trigger: '[unclosed'", 1
        )
        response = await http.post(
            f"/api/review-packs/{pack_id}/versions",
            json={"version": "0.3.1", "files": {"template": broken}},
        )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "TEMPLATE_INVALID"
    # На диске не осталось ни каталога, ни записи: сборка идёт во временном
    # месте и переносится только после подтверждения ядром.
    assert not (settings.review_packs_dir / "mts-net" / "0.3.1").exists()


@pytest.mark.anyio
async def test_broken_yaml_is_rejected_with_the_core_reason(authoring):
    settings, pack_id = authoring
    async with client(settings) as http:
        response = await http.post(
            f"/api/review-packs/{pack_id}/versions",
            json={"version": "0.4.1", "files": {"policy": "ceiling: [\n"}},
        )
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "POLICY_INVALID"
    # Причина от ядра доходит дословно: иначе человек не поймёт, что чинить.
    assert body["message"]


@pytest.mark.anyio
async def test_core_message_does_not_leak_the_staging_path(authoring):
    """Путь временного каталога не уходит в браузер.

    Ядро называет файл абсолютным путём, а проверяем мы копию пакета
    в системном временном каталоге. Человек видел «политика
    /tmp/pack-tnxjped_/pack/policy.yaml не читается» — путь, которого
    к моменту показа уже нет: чинить по нему нечего, а наружу уходит
    схема именования и сам факт сборки в /tmp.
    """
    settings, pack_id = authoring
    async with client(settings) as http:
        response = await http.post(
            f"/api/review-packs/{pack_id}/versions",
            json={"version": "0.4.2", "files": {"policy": "ceiling: [\n"}},
        )
    message = response.json()["error"]["message"]
    assert "/tmp" not in message and "/var/folders" not in message, message
    assert "pack-" not in message, message
    # И при этом остаётся сказанным, ЧТО чинить.
    assert "policy.yaml" in message, message


@pytest.mark.anyio
async def test_version_taken_during_validation_does_not_corrupt_it(authoring, monkeypatch):
    """Гонка по одному номеру версии не портит опубликованную версию.

    Между проверкой `target.exists()` и переносом идёт валидация ядром —
    до минуты. Если за это время номер занял другой выпускающий,
    `shutil.move` клал каталог сборки ВНУТРЬ занятой версии: в артефакт,
    объявленный неизменяемым, дописывался подкаталог `pack`, и запрос
    при этом завершался успехом.
    """
    settings, pack_id = authoring
    target = settings.review_packs_dir / "mts-net" / "0.9"
    original = ReviewPackCatalogService._validate_with_core

    def validate_then_squat(self, draft: Path) -> None:
        original(self, draft)
        target.mkdir(parents=True)
        (target / "policy.yaml").write_text("ceiling: 20\n", encoding="utf-8")

    monkeypatch.setattr(ReviewPackCatalogService, "_validate_with_core", validate_then_squat)

    async with client(settings) as http:
        source = (await http.get(f"/api/review-packs/{pack_id}/source")).json()
        response = await http.post(
            f"/api/review-packs/{pack_id}/versions",
            json={"version": "0.9", "files": {"policy": source["files"]["policy"]}},
        )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "REVIEW_PACK_VERSION_EXISTS"
    # Чужая версия осталась ровно тем, чем была.
    assert sorted(p.name for p in target.iterdir()) == ["policy.yaml"]


@pytest.mark.anyio
async def test_version_registered_during_validation_gives_409_not_500(authoring, monkeypatch):
    """Уникальный индекс — последний рубеж, и он обязан звучать как 409.

    Запись могла появиться уже после `_version_registered`. Неперехваченный
    IntegrityError уходил наружу пятисоткой INTERNAL_ERROR: человек видел
    «внутренняя ошибка» там, где на самом деле занят номер версии.

    Плюс проверка компенсации: каталог уже перенесён в боевой корень,
    а записи за ним нет. Оставить его — значит выжечь номер версии
    навсегда, `target.exists()` истинно и каждая следующая попытка
    получает 409 на профиль, которого нет ни в каталоге, ни в базе.
    """
    settings, pack_id = authoring
    target = settings.review_packs_dir / "mts-net" / "0.9"
    original = ReviewPackCatalogService._validate_with_core

    def validate_then_register(self, draft: Path) -> None:
        original(self, draft)
        with self._session_factory.begin() as session:
            session.add(
                ReviewPackReferenceModel(
                    company_id=settings.default_company_id,
                    pack_key="mts-net",
                    version="0.9",
                    display_name="Гонка",
                    document_type="technical_specification",
                    locator="mts-net/0.9",
                )
            )

    monkeypatch.setattr(ReviewPackCatalogService, "_validate_with_core", validate_then_register)

    async with client(settings) as http:
        source = (await http.get(f"/api/review-packs/{pack_id}/source")).json()
        response = await http.post(
            f"/api/review-packs/{pack_id}/versions",
            json={"version": "0.9", "files": {"policy": source["files"]["policy"]}},
        )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "REVIEW_PACK_VERSION_EXISTS"
    assert not target.exists(), sorted(p.name for p in target.iterdir())


@pytest.mark.anyio
async def test_failed_registration_frees_the_version_number(authoring, monkeypatch):
    """Отказ вставки не оставляет каталог без записи.

    Отдельно от предыдущего теста: там отказ ожидаемый (номер занят),
    здесь — любой другой сбой БД. Разница важна, потому что выжигание
    номера происходит одинаково в обоих случаях, а чинилось бы одним
    перехватом IntegrityError только в первом.
    """
    settings, pack_id = authoring
    target = settings.review_packs_dir / "mts-net" / "0.9"

    async with client(settings) as http:
        source = (await http.get(f"/api/review-packs/{pack_id}/source")).json()

        def explode(self, **_kwargs):
            raise RuntimeError("соединение с базой потеряно")

        # Ломаем создание самой записи: это ровно тот момент, после которого
        # каталог уже в боевом корне, а строки в базе ещё нет.
        monkeypatch.setattr(ReviewPackReferenceModel, "__init__", explode)
        # Обработчик Exception в приложении отвечает 500, но Starlette
        # после него исключение пробрасывает — тестовый клиент видит его.
        with pytest.raises(RuntimeError):
            await http.post(
                f"/api/review-packs/{pack_id}/versions",
                json={"version": "0.9", "files": {"policy": source["files"]["policy"]}},
            )

    # Номер версии свободен: следующая попытка не упрётся в каталог-призрак.
    assert not target.exists()


@pytest.mark.anyio
@pytest.mark.parametrize("version", ["../escape", "0.2/../0.3", "", "a" * 60, "с пробелом"])
async def test_unsafe_versions_are_rejected(authoring, version):
    settings, pack_id = authoring
    async with client(settings) as http:
        response = await http.post(
            f"/api/review-packs/{pack_id}/versions",
            json={"version": version, "files": {"policy": "ceiling: 20\n"}},
        )
    assert response.status_code in (409, 422), (version, response.status_code)
    assert not (settings.review_packs_dir / "escape").exists()


@pytest.mark.anyio
async def test_unknown_file_key_is_rejected(authoring):
    """Править можно только то, что применяет ядро."""
    settings, pack_id = authoring
    async with client(settings) as http:
        response = await http.post(
            f"/api/review-packs/{pack_id}/versions",
            json={"version": "0.5.1", "files": {"model-config": "base_url: x\n"}},
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REVIEW_PACK_FILE_UNKNOWN"


@pytest.mark.anyio
async def test_foreign_pack_is_not_readable(authoring, database_url):
    """Пакет чужого арендатора не читается и не правится."""
    settings, _pack_id = authoring
    foreign_engine = create_database_engine(database_url)
    sessions = create_session_factory(foreign_engine)
    with sessions.begin() as session:
        foreign = CompanyModel(slug="foreign", display_name="Foreign")
        session.add(foreign)
        session.flush()
        record = ReviewPackReferenceModel(
            company_id=foreign.id,
            pack_key="mts-net",
            version="0.2",
            display_name="Чужой",
            document_type="technical_specification",
            locator="mts-net/0.2",
        )
        session.add(record)
        session.flush()
        foreign_pack_id = record.id
    try:
        async with client(settings) as http:
            response = await http.get(f"/api/review-packs/{foreign_pack_id}/source")
    finally:
        foreign_engine.dispose()
    assert response.status_code == 404


@pytest.mark.anyio
async def test_missing_validator_is_reported_as_unavailable(authoring, tmp_path):
    """Если команды ядра нет, это отказ сервиса, а не «пакет невалиден».

    Разница существенная: в первом случае чинить нечего пользователю,
    во втором он будет искать ошибку в своём YAML.
    """
    settings, pack_id = authoring
    settings = settings.model_copy(
        update={"analysis_executable": str(tmp_path / "нет-такой-команды")}
    )
    async with client(settings) as http:
        response = await http.post(
            f"/api/review-packs/{pack_id}/versions",
            json={"version": "0.6.1", "files": {"policy": "ceiling: 20\n"}},
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "REVIEW_PACK_VALIDATOR_UNAVAILABLE"
