import pytest

from app.db.repository import Repository
from app.operations.center import OperationsCenter
from tests.operations_support import Sleeps, make_center


@pytest.fixture
def sleeps() -> Sleeps:
    """Un `sleep` che non aspetta e registra i ritardi chiesti."""
    return Sleeps()


@pytest.fixture
def center(repo: Repository, sleeps: Sleeps) -> OperationsCenter:
    return make_center(repo, sleeps)
