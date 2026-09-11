from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _sample_saves() -> list[Path]:
    # Personal saves are gitignored; tests use whatever is present locally.
    return sorted((ROOT / "tests" / "fixtures").glob("*.fch")) or sorted((ROOT / "Save").glob("*.fch"))


@pytest.fixture
def sample_bytes() -> bytes:
    saves = _sample_saves()
    if not saves:
        pytest.skip("no .fch fixture: copy a save into tests/fixtures/ (see README.txt there)")
    return saves[0].read_bytes()
