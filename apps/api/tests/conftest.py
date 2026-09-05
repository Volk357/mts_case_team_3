import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

# Адрес PostgreSQL для тестов. Тесты идут на той же СУБД, что и продукт:
# SQLite из проекта убран, и подменять её в тестах значило бы проверять
# другую модель параллелизма, чем та, что поставляется.
ADMIN_DATABASE_URL = os.environ.get(
    "DOCREVIEW_TEST_DATABASE_URL",
    "postgresql+psycopg://docreview@localhost/docreview",
)


@pytest.fixture
def anyio_backend() -> str:
    """Run ASGI tests on asyncio only; Trio is not an application dependency."""

    return "asyncio"


@pytest.fixture
def database_url() -> Iterator[str]:
    """Своя пустая база на каждый тест.

    Отдельная база, а не общая со сбросом таблиц: тесты трогают внешние ключи
    и последовательности, и остатки соседнего теста дают плавающие падения,
    которые дороже, чем создание базы.
    """

    admin = create_engine(ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT")
    name = f"docreview_test_{uuid4().hex[:16]}"
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()

    url = ADMIN_DATABASE_URL.rsplit("/", 1)[0] + f"/{name}"
    try:
        yield url
    finally:
        admin = create_engine(ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            # Открытые соединения не дают удалить базу; закрываем их сами,
            # иначе упавший тест утащил бы за собой всю сессию прогона.
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        admin.dispose()
