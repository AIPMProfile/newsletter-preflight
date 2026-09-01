import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

from preflight.evals.generate import SAMPLES_DIR, load_ground_truth, write_all  # noqa: E402


@pytest.fixture(scope="session")
def corpus():
    write_all()
    return SAMPLES_DIR


@pytest.fixture(scope="session")
def ground_truth(corpus):
    return load_ground_truth()


@pytest.fixture(autouse=True)
def _no_side_effect_logs(tmp_path, monkeypatch):
    """Keep the suite from writing into the repo.

    `eval` appends a row to the benchmark history and `audit` can append to the
    monitor log. Both are real behaviour worth testing, and neither belongs in
    tracked files just because someone ran pytest - a history full of test rows
    stops being a record of what the agent scored.

    Tests that exercise logging on purpose override these with their own paths.
    """
    monkeypatch.setenv("PREFLIGHT_HISTORY_LOG", str(tmp_path / "history.jsonl"))
    monkeypatch.setenv("PREFLIGHT_MONITOR_LOG", str(tmp_path / "audits.jsonl"))
    monkeypatch.delenv("PREFLIGHT_MONITOR", raising=False)
