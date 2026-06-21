import pytest
from app.config import database


@pytest.fixture(scope="session", autouse=True)
def event_loop():
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def anyio_backend():
    return 'asyncio'
