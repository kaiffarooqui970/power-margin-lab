import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fixtures import synthetic  # noqa: E402


@pytest.fixture(scope="session")
def synthetic_root(tmp_path_factory) -> Path:
    return synthetic.make(tmp_path_factory.mktemp("synthetic_data"))
