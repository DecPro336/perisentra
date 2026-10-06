from datetime import date

import pytest
from fernbrook.world import World
from worlds import make_world


@pytest.fixture(scope="session")
def world() -> World:
    return make_world(date(2025, 3, 31))
