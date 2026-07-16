from __future__ import annotations

from pathlib import Path

import pytest

from kol_sniper.config import Settings
from kol_sniper.storage import Store

MINT = "4t1xhKJd6oFGr98oWJoxYjLU74eFe7xiYSRDoX18pump"
WALLET = "9xQeWvG816bUx9EPfEZ7vVfNqK3mVZp8dNhkZ8sKZ5xV"


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "state.db")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(database_path=tmp_path / "state.db", dry_run=True)
