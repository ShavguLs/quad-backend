"""Root pytest configuration with shared fixtures."""
import os
import pytest
from pathlib import Path

# Add project root to path for imports
BASE_DIR = Path(__file__).parent


@pytest.fixture(scope="session")
def regression_fixtures_dir():
    """Return path to regression fixtures directory."""
    return BASE_DIR / "apps" / "books" / "tests" / "fixtures" / "regression"


@pytest.fixture(scope="session")
def sample_pdfs_dir():
    """Return path to sample PDF fixtures."""
    return BASE_DIR / "apps" / "books" / "tests" / "fixtures" / "regression" / "source"


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "regression: marks tests as regression tests"
    )
