import os

import pytest

os.environ.setdefault("AI_MOCK_MODE", "always")


@pytest.fixture()
def anyio_backend():
    return "asyncio"
