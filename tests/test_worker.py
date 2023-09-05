import pytest
from fatcat_worker import Worker


@pytest.fixture
def worker() -> Worker:
    return Worker()


def test_git(worker: Worker):
    worker.clone_worker()


def test_install_deps(worker: Worker):
    worker.install_worker_deps()


@pytest.mark.asyncio
async def test_load_worker(worker: Worker):
    await worker.load_worker()
