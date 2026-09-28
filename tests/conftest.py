import os
import tempfile
from pathlib import Path

import pytest

# The app reads its output directory at import time, so point it at a scratch build first.
BUILD_DIR = Path(tempfile.mkdtemp(prefix="serviceops-test-"))
os.environ["SERVICEOPS_OUTPUT"] = str(BUILD_DIR)

from serviceops.db import Database  # noqa: E402
from serviceops.pipeline import build  # noqa: E402
from serviceops.quality import run_quality_gate  # noqa: E402
from serviceops.simulate import export_raw, simulate  # noqa: E402


@pytest.fixture(scope="session")
def clean_history():
    return simulate()


@pytest.fixture(scope="session")
def raw_and_key(clean_history):
    return export_raw(clean_history)


@pytest.fixture(scope="session")
def gated(raw_and_key):
    return run_quality_gate(raw_and_key[0])


@pytest.fixture(scope="session")
def built():
    """One full pipeline run (SQLite, Excel, Power BI export) shared by the suite."""
    return build(out_dir=BUILD_DIR)


@pytest.fixture(scope="session")
def db(built):
    database = Database(built.db_url)
    yield database
    database.close()
