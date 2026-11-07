import os, sys, tempfile
import pytest

# Tests never touch real data: a throw-away data dir and database, set before anything imports app.config.
_TMP = tempfile.mkdtemp(prefix="smartdoc-test-")
os.environ["SMARTDOC_DATA_DIR"] = _TMP
os.environ["SMARTDOC_DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["SMARTDOC_SECRET"] = "test-secret-" + "x" * 32
os.environ.pop("SMARTDOC_ENV", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tests.make_templates import build_all
from tests.sample import make_image


@pytest.fixture(scope="session")
def templates(tmp_path_factory):
    return build_all(str(tmp_path_factory.mktemp("tpl")))


@pytest.fixture(scope="session")
def image(tmp_path_factory):
    return make_image(str(tmp_path_factory.mktemp("img") / "a.png"))


from app.document_engine.pdf import soffice_path

needs_soffice = pytest.mark.skipif(soffice_path() is None, reason="LibreOffice not installed")


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c
