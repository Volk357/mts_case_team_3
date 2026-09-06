from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from docreview_api.config import Settings
from docreview_api.db.base import Base
from docreview_api.db.models import CompanyModel, ReviewPackReferenceModel
from docreview_api.db.session import create_database_engine, create_session_factory
from docreview_api.main import create_app


@pytest.fixture
def catalog_settings(tmp_path: Path, database_url: str) -> tuple[Settings, UUID, UUID]:
    packs_root = tmp_path / "review-packs"
    (packs_root / "requirements-v1").mkdir(parents=True)
    (packs_root / "requirements-v1" / "pack.yaml").write_text(
        "id: requirements\nversion: '1.0'\n", encoding="utf-8"
    )
    # Три файла настройки лежат, четвёртый (policy.yaml) намеренно нет:
    # интерфейс обязан показать его как отсутствующий, а не скрыть.
    for name in ("template.yaml", "defects.yaml", "glossary.yaml"):
        (packs_root / "requirements-v1" / name).write_text("{}\n", encoding="utf-8")
    (packs_root / "inactive").mkdir()
    (packs_root / "inactive" / "pack.yaml").write_text("version: '1.0'\n", encoding="utf-8")
    (packs_root / "foreign").mkdir()
    (packs_root / "foreign" / "pack.yaml").write_text("version: '1.0'\n", encoding="utf-8")
    (packs_root / "empty").mkdir()

    settings = Settings(
        environment="test",
        database_url=database_url,
        review_packs_dir=packs_root,
        _env_file=None,
    )
    engine = create_database_engine(settings.database_url)
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        company = CompanyModel(
            id=settings.default_company_id,
            slug=settings.default_company_slug,
            display_name=settings.default_company_name,
        )
        foreign_company = CompanyModel(slug="foreign", display_name="Foreign")
        session.add_all([company, foreign_company])
        session.flush()
        visible = ReviewPackReferenceModel(
            company_id=company.id,
            pack_key="requirements",
            version="1.0",
            display_name="Requirements",
            document_type="technical_specification",
            locator="requirements-v1",
        )
        session.add_all(
            [
                visible,
                ReviewPackReferenceModel(
                    company_id=company.id,
                    pack_key="inactive",
                    version="1.0",
                    display_name="Inactive",
                    document_type="technical_specification",
                    locator="inactive",
                    is_active=False,
                ),
                ReviewPackReferenceModel(
                    company_id=company.id,
                    pack_key="missing",
                    version="1.0",
                    display_name="Missing",
                    document_type="technical_specification",
                    locator="missing",
                ),
                ReviewPackReferenceModel(
                    company_id=company.id,
                    pack_key="unsafe",
                    version="1.0",
                    display_name="Unsafe",
                    document_type="technical_specification",
                    locator="../outside",
                ),
                ReviewPackReferenceModel(
                    company_id=company.id,
                    pack_key="empty",
                    version="1.0",
                    display_name="Empty directory",
                    document_type="technical_specification",
                    locator="empty",
                ),
                ReviewPackReferenceModel(
                    company_id=foreign_company.id,
                    pack_key="foreign",
                    version="1.0",
                    display_name="Foreign",
                    document_type="technical_specification",
                    locator="foreign",
                ),
            ]
        )
        session.flush()
        visible_id = visible.id
        foreign_id = foreign_company.id
    engine.dispose()
    return settings, visible_id, foreign_id


@pytest.mark.anyio
async def test_catalog_returns_only_active_valid_tenant_packs_without_locator(
    catalog_settings: tuple[Settings, UUID, UUID],
) -> None:
    settings, visible_id, _ = catalog_settings
    app = create_app(settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/review-packs")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "review_pack_id": str(visible_id),
                "display_name": "Requirements",
                "document_type": "technical_specification",
                "version": "1.0",
                "contents": [
                    {
                        "key": "template",
                        "filename": "template.yaml",
                        "description": (
                            "Структура документа: какие разделы обязательны и что в них проверяется"
                        ),
                        "present": True,
                    },
                    {
                        "key": "defects",
                        "filename": "defects.yaml",
                        "description": (
                            "Таксономия дефектов и конвенции компании — что считать ошибкой"
                        ),
                        "present": True,
                    },
                    {
                        "key": "glossary",
                        "filename": "glossary.yaml",
                        "description": "Термины, которые в компании не расшифровывают",
                        "present": True,
                    },
                    {
                        "key": "policy",
                        "filename": "policy.yaml",
                        "description": (
                            "Политика приёмки: сколько замечаний показывать "
                            "и что дороже — пропуск или шум"
                        ),
                        "present": False,
                    },
                ],
                # policy.yaml в этом пакете отсутствует, склонность неизвестна.
                "policy_bias": None,
            }
        ],
        "total": 1,
    }
    assert "locator" not in response.text
    assert "checksum" not in response.text
    assert str(settings.review_packs_dir) not in response.text


@pytest.mark.anyio
async def test_catalog_is_declared_in_openapi(
    catalog_settings: tuple[Settings, UUID, UUID],
) -> None:
    settings, _, _ = catalog_settings
    app = create_app(settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        schema = (await client.get("/api/openapi.json")).json()

    operation = schema["paths"]["/api/review-packs"]["get"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ReviewPackListResponse"
    }
    public_fields = schema["components"]["schemas"]["ReviewPackResponse"]["properties"]
    assert set(public_fields) == {
        "review_pack_id",
        "display_name",
        "document_type",
        "version",
        "contents",
        "policy_bias",
    }


@pytest.mark.anyio
async def test_pack_contents_report_missing_file_instead_of_hiding_it(
    catalog_settings: tuple[Settings, UUID, UUID],
) -> None:
    """Отсутствующий файл настройки показывается как отсутствующий.

    Скрыть его значило бы показать пакет полнее, чем он есть: человек
    не узнал бы, что политика приёмки в этом пакете не задана и работают
    умолчания ядра.
    """
    settings, _, _ = catalog_settings
    app = create_app(settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/review-packs")

    contents = response.json()["items"][0]["contents"]
    assert [part["key"] for part in contents] == ["template", "defects", "glossary", "policy"]
    assert [part["present"] for part in contents] == [True, True, True, False]


@pytest.mark.anyio
async def test_pack_contents_do_not_leak_filesystem_paths(
    catalog_settings: tuple[Settings, UUID, UUID],
) -> None:
    """Наружу идут имена файлов, а не пути на диске сервера."""
    settings, _, _ = catalog_settings
    app = create_app(settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/review-packs")

    assert str(settings.review_packs_dir) not in response.text
    assert "requirements-v1" not in response.text
    for part in response.json()["items"][0]["contents"]:
        assert "/" not in part["filename"]


@pytest.mark.anyio
async def test_pack_contents_follow_manifest_filenames(tmp_path: Path, database_url: str) -> None:
    """Имя файла берётся из манифеста, а не из соглашения.

    Блокер ревью: пакет с `policy: strict.yaml` показывал бы «policy.yaml
    не задан, работают умолчания», хотя политика задана и применяется ядром.
    Интерфейс сообщал бы неправду про действующие настройки.
    """
    packs_root = tmp_path / "review-packs"
    pack = packs_root / "custom"
    pack.mkdir(parents=True)
    (pack / "pack.yaml").write_text(
        "id: custom\nversion: '2.0'\ncontents:\n  policy: strict.yaml\n",
        encoding="utf-8",
    )
    (pack / "strict.yaml").write_text("ceiling: 5\n", encoding="utf-8")

    settings = Settings(
        environment="test",
        database_url=database_url,
        review_packs_dir=packs_root,
        _env_file=None,
    )
    engine = create_database_engine(settings.database_url)
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        company = CompanyModel(
            id=settings.default_company_id,
            slug=settings.default_company_slug,
            display_name=settings.default_company_name,
        )
        session.add(company)
        session.flush()
        session.add(
            ReviewPackReferenceModel(
                company_id=company.id,
                pack_key="custom",
                version="2.0",
                display_name="Custom",
                document_type="technical_specification",
                locator="custom",
            )
        )
    engine.dispose()

    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/review-packs")

    contents = {part["key"]: part for part in response.json()["items"][0]["contents"]}
    assert contents["policy"]["filename"] == "strict.yaml"
    assert contents["policy"]["present"] is True
    # Остальные три ядро резолвит ФИКСИРОВАННО, манифест на них не влияет —
    # показать здесь манифестное имя значило бы объявить применяемым файл,
    # который ядро проигнорирует.
    assert contents["template"]["filename"] == "template.yaml"
    assert contents["template"]["present"] is False


@pytest.mark.anyio
async def test_broken_policy_declaration_hides_contents(tmp_path: Path, database_url: str) -> None:
    """Негодное объявление политики — состав не показывается вовсе.

    Блокер ревью: раньше такое объявление молча заменялось соглашением,
    и интерфейс показывал рабочий состав. Но ядро отвергает такой пакет
    целиком (ReviewPackInvalid) — проверка по нему не запустится, и обещать
    её нельзя.
    """
    packs_root = tmp_path / "review-packs"
    pack = packs_root / "escaping"
    pack.mkdir(parents=True)
    (pack / "pack.yaml").write_text(
        "id: escaping\nversion: '1.0'\ncontents:\n  policy: ../../etc/passwd\n",
        encoding="utf-8",
    )

    settings = Settings(
        environment="test",
        database_url=database_url,
        review_packs_dir=packs_root,
        _env_file=None,
    )
    engine = create_database_engine(settings.database_url)
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        company = CompanyModel(
            id=settings.default_company_id,
            slug=settings.default_company_slug,
            display_name=settings.default_company_name,
        )
        session.add(company)
        session.flush()
        session.add(
            ReviewPackReferenceModel(
                company_id=company.id,
                pack_key="escaping",
                version="1.0",
                display_name="Escaping",
                document_type="technical_specification",
                locator="escaping",
            )
        )
    engine.dispose()

    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/review-packs")

    assert response.json()["items"][0]["contents"] == []
    assert "passwd" not in response.text


@pytest.mark.anyio
async def test_manifest_names_apply_only_to_policy(tmp_path: Path, database_url: str) -> None:
    """Ядро читает из манифеста только `policy` — API обязан вести себя так же.

    Блокер ревью: API применял манифестные имена ко всем четырём ролям,
    и для `defects: custom.yaml` показал бы применяемым файл, который ядро
    не читает (оно берёт фиксированный `defects.yaml`).
    """
    packs_root = tmp_path / "review-packs"
    pack = packs_root / "partial"
    pack.mkdir(parents=True)
    (pack / "pack.yaml").write_text(
        "id: partial\nversion: '1.0'\n"
        "contents:\n  defects: custom-defects.yaml\n  template: custom-template.yaml\n",
        encoding="utf-8",
    )
    (pack / "custom-defects.yaml").write_text("{}\n", encoding="utf-8")
    (pack / "defects.yaml").write_text("{}\n", encoding="utf-8")

    settings = Settings(
        environment="test",
        database_url=database_url,
        review_packs_dir=packs_root,
        _env_file=None,
    )
    engine = create_database_engine(settings.database_url)
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        company = CompanyModel(
            id=settings.default_company_id,
            slug=settings.default_company_slug,
            display_name=settings.default_company_name,
        )
        session.add(company)
        session.flush()
        session.add(
            ReviewPackReferenceModel(
                company_id=company.id,
                pack_key="partial",
                version="1.0",
                display_name="Partial",
                document_type="technical_specification",
                locator="partial",
            )
        )
    engine.dispose()

    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/review-packs")

    contents = {part["key"]: part for part in response.json()["items"][0]["contents"]}
    assert contents["defects"]["filename"] == "defects.yaml"
    assert contents["defects"]["present"] is True
    assert contents["template"]["filename"] == "template.yaml"
    assert "custom-defects.yaml" not in response.text


@pytest.mark.anyio
async def test_locator_pointing_at_manifest_file_is_read(tmp_path: Path, database_url: str) -> None:
    """Локатор на сам манифест: читается указанный файл, а не `pack.yaml` рядом.

    Блокер ревью: раньше брался только родительский каталог и искался
    `pack.yaml`, поэтому объявленная политика терялась.
    """
    packs_root = tmp_path / "review-packs"
    pack = packs_root / "by-file"
    pack.mkdir(parents=True)
    (pack / "custom.yaml").write_text(
        "id: by-file\nversion: '1.0'\ncontents:\n  policy: strict.yaml\n", encoding="utf-8"
    )
    (pack / "strict.yaml").write_text("ceiling: 5\n", encoding="utf-8")

    settings = Settings(
        environment="test",
        database_url=database_url,
        review_packs_dir=packs_root,
        _env_file=None,
    )
    engine = create_database_engine(settings.database_url)
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        company = CompanyModel(
            id=settings.default_company_id,
            slug=settings.default_company_slug,
            display_name=settings.default_company_name,
        )
        session.add(company)
        session.flush()
        session.add(
            ReviewPackReferenceModel(
                company_id=company.id,
                pack_key="by-file",
                version="1.0",
                display_name="By file",
                document_type="technical_specification",
                locator="by-file/custom.yaml",
            )
        )
    engine.dispose()

    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/review-packs")

    contents = {part["key"]: part for part in response.json()["items"][0]["contents"]}
    assert contents["policy"]["filename"] == "strict.yaml"
    assert contents["policy"]["present"] is True


@pytest.mark.anyio
async def test_incomplete_manifest_hides_contents(tmp_path: Path, database_url: str) -> None:
    """Манифест без id/version — состав не показывается.

    Найдено сверкой с ядром: оно объявляет манифест источником истины
    и без идентичности отвергает пакет целиком. Показать состав значило бы
    обещать проверку, которая не запустится.
    """
    packs_root = tmp_path / "review-packs"
    pack = packs_root / "nameless"
    pack.mkdir(parents=True)
    (pack / "pack.yaml").write_text("contents:\n  policy: strict.yaml\n", encoding="utf-8")
    (pack / "strict.yaml").write_text("ceiling: 5\n", encoding="utf-8")

    settings = Settings(
        environment="test",
        database_url=database_url,
        review_packs_dir=packs_root,
        _env_file=None,
    )
    engine = create_database_engine(settings.database_url)
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        company = CompanyModel(
            id=settings.default_company_id,
            slug=settings.default_company_slug,
            display_name=settings.default_company_name,
        )
        session.add(company)
        session.flush()
        session.add(
            ReviewPackReferenceModel(
                company_id=company.id,
                pack_key="nameless",
                version="1.0",
                display_name="Nameless",
                document_type="technical_specification",
                locator="nameless",
            )
        )
    engine.dispose()

    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/review-packs")

    assert response.json()["items"][0]["contents"] == []


def _single_pack_settings(packs_root: Path, database_url: str, locator: str) -> Settings:
    """Каталог с одним пакетом — общая обвязка для проверок манифеста."""
    settings = Settings(
        environment="test",
        database_url=database_url,
        review_packs_dir=packs_root,
        _env_file=None,
    )
    engine = create_database_engine(settings.database_url)
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        company = CompanyModel(
            id=settings.default_company_id,
            slug=settings.default_company_slug,
            display_name=settings.default_company_name,
        )
        session.add(company)
        session.flush()
        session.add(
            ReviewPackReferenceModel(
                company_id=company.id,
                pack_key="probe",
                version="1.0",
                display_name="Probe",
                document_type="technical_specification",
                locator=locator,
            )
        )
    engine.dispose()
    return settings


async def _contents_of(settings: Settings) -> list[dict[str, object]]:
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/review-packs")
    assert response.status_code == 200
    return list(response.json()["items"][0]["contents"])


@pytest.mark.anyio
async def test_declared_policy_file_must_exist(tmp_path: Path, database_url: str) -> None:
    """Объявленный файл политики отсутствует — состав не показывается.

    Ядро отвергает такой пакет («объявляет contents.policy, но файла нет»).
    Показать `present: false` значило бы выдать нерабочий пакет за рабочий
    с пустой политикой.
    """
    packs_root = tmp_path / "review-packs"
    pack = packs_root / "probe"
    pack.mkdir(parents=True)
    (pack / "pack.yaml").write_text(
        "id: probe\nversion: '1.0'\ncontents:\n  policy: strict.yaml\n", encoding="utf-8"
    )

    assert await _contents_of(_single_pack_settings(packs_root, database_url, "probe")) == []


@pytest.mark.anyio
async def test_declared_policy_symlink_outside_pack_hides_contents(
    tmp_path: Path, database_url: str
) -> None:
    """Симлинк наружу проходит is_file(), но ядро пакет отвергает."""
    packs_root = tmp_path / "review-packs"
    pack = packs_root / "probe"
    pack.mkdir(parents=True)
    (pack / "pack.yaml").write_text(
        "id: probe\nversion: '1.0'\ncontents:\n  policy: strict.yaml\n", encoding="utf-8"
    )
    outside = tmp_path / "outside.yaml"
    outside.write_text("ceiling: 5\n", encoding="utf-8")
    (pack / "strict.yaml").symlink_to(outside)

    assert await _contents_of(_single_pack_settings(packs_root, database_url, "probe")) == []


@pytest.mark.anyio
async def test_null_contents_differs_from_missing_key(tmp_path: Path, database_url: str) -> None:
    """`contents:` без значения — сломанный манифест, а не отсутствие ключа."""
    packs_root = tmp_path / "review-packs"
    pack = packs_root / "probe"
    pack.mkdir(parents=True)
    (pack / "pack.yaml").write_text("id: probe\nversion: '1.0'\ncontents:\n", encoding="utf-8")

    assert await _contents_of(_single_pack_settings(packs_root, database_url, "probe")) == []


@pytest.mark.anyio
async def test_manifest_in_foreign_encoding_does_not_break_catalog(
    tmp_path: Path, database_url: str
) -> None:
    """Манифест в чужой кодировке не роняет весь каталог пятисоткой.

    UnicodeDecodeError не входит ни в OSError, ни в yaml.YAMLError: один
    повреждённый пакет обрушивал бы `/api/review-packs`, а с ним и главный
    экран, где идёт загрузка документа.
    """
    packs_root = tmp_path / "review-packs"
    pack = packs_root / "probe"
    pack.mkdir(parents=True)
    (pack / "pack.yaml").write_bytes("id: probe\nversion: '1.0'\n# кириллица\n".encode("cp1251"))

    assert await _contents_of(_single_pack_settings(packs_root, database_url, "probe")) == []


@pytest.mark.anyio
async def test_conventional_policy_symlink_outside_pack_hides_contents(
    tmp_path: Path, database_url: str
) -> None:
    """Та же дыра там, где имя НЕ объявлено в манифесте.

    Найдено на ревью: проверка realpath стояла внутри ветки объявленного
    имени, и `policy.yaml`, подложенный симлинком наружу, показывался
    как применяемый. Ядро такой пакет отвергает — политика читалась бы
    из неверсионируемого места.

    Ровно эта же ошибка была допущена и исправлена в самом ядре в тот же
    день; здесь она была воспроизведена в API.
    """
    packs_root = tmp_path / "review-packs"
    pack = packs_root / "probe"
    pack.mkdir(parents=True)
    (pack / "pack.yaml").write_text("id: probe\nversion: '1.0'\n", encoding="utf-8")
    outside = tmp_path / "outside.yaml"
    outside.write_text("ceiling: 5\n", encoding="utf-8")
    (pack / "policy.yaml").symlink_to(outside)

    assert await _contents_of(_single_pack_settings(packs_root, database_url, "probe")) == []


@pytest.mark.anyio
async def test_conventional_policy_absence_is_normal(tmp_path: Path, database_url: str) -> None:
    """Файла по соглашению может не быть — это рабочий пакет на умолчаниях.

    Отличие от объявленного имени: там отсутствие файла делает пакет
    нерабочим, здесь — нет. Схлопывать эти случаи нельзя.
    """
    packs_root = tmp_path / "review-packs"
    pack = packs_root / "probe"
    pack.mkdir(parents=True)
    (pack / "pack.yaml").write_text("id: probe\nversion: '1.0'\n", encoding="utf-8")
    (pack / "template.yaml").write_text("{}\n", encoding="utf-8")

    contents = await _contents_of(_single_pack_settings(packs_root, database_url, "probe"))
    by_key = {part["key"]: part for part in contents}
    assert by_key["policy"]["present"] is False
    assert by_key["template"]["present"] is True


@pytest.mark.anyio
async def test_policy_bias_is_exposed_from_the_pack(tmp_path: Path, database_url: str) -> None:
    """Склонность приёмки уходит в каталог: по ней человек выбирает профиль."""
    packs_root = tmp_path / "review-packs"
    pack = packs_root / "probe"
    pack.mkdir(parents=True)
    (pack / "pack.yaml").write_text("id: probe\nversion: '1.0'\n", encoding="utf-8")
    (pack / "policy.yaml").write_text("bias: precision\nceiling: 12\n", encoding="utf-8")

    app = create_app(_single_pack_settings(packs_root, database_url, "probe"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/review-packs")

    assert response.json()["items"][0]["policy_bias"] == "precision"


@pytest.mark.anyio
async def test_unknown_policy_bias_is_not_exposed(tmp_path: Path, database_url: str) -> None:
    """Незнакомая склонность не показывается вовсе.

    policy.yaml лежит на диске и мог быть собран как угодно; показать
    непонятную метку в выборе профиля хуже, чем не показать ничего.
    """
    packs_root = tmp_path / "review-packs"
    pack = packs_root / "probe"
    pack.mkdir(parents=True)
    (pack / "pack.yaml").write_text("id: probe\nversion: '1.0'\n", encoding="utf-8")
    (pack / "policy.yaml").write_text("bias: whatever\n", encoding="utf-8")

    app = create_app(_single_pack_settings(packs_root, database_url, "probe"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/review-packs")

    assert response.json()["items"][0]["policy_bias"] is None
    assert "whatever" not in response.text
