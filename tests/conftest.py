import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="speedtest-logger-tests-")
os.environ.pop("TELEGRAM_BOT_TOKEN", None)
os.environ.pop("HEARTBEAT_URL", None)

import pytest

from backend.api import app
from backend.database import Base, engine


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def no_network_probes(monkeypatch):
    from collector import probe

    def blocked(*args, **kwargs):
        raise OSError("network probes are disabled in tests")

    monkeypatch.setattr(probe, "ping", blocked)
    monkeypatch.setattr(probe, "async_multiping", blocked)
