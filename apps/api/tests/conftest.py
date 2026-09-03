import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Run ASGI tests on asyncio only; Trio is not an application dependency."""

    return "asyncio"
