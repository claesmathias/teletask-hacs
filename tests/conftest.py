import asyncio
import json
from pathlib import Path
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--config",
        default=str(Path(__file__).parent.parent / "config.json"),
        help="Path to the Teletask config JSON file (default: config.json in repo root)",
    )


@pytest.fixture(scope="session")
def teletask_config(request):
    path = Path(request.config.getoption("--config"))
    return json.loads(path.read_text())


@pytest.fixture(autouse=True)
async def inter_test_cooldown():
    """Give the central time to clean up between tests.

    The Picos central needs a brief pause after a client disconnects before it
    will accept new LOG subscriptions from the next client.  Without this, rapid
    back-to-back connections in the test suite cause the central to RST the
    connection as soon as subscriptions are sent.
    """
    yield
    await asyncio.sleep(2.0)
