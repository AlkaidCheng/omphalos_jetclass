from collections.abc import Mapping

import pytest

from omphjc.processes import ProcessSpec, catalogue


@pytest.fixture(scope="session")
def specs() -> Mapping[str, ProcessSpec]:
    return catalogue()
