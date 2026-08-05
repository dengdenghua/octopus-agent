from pathlib import Path

import pytest

from benchmarks.validate_result_manifest import validate_manifest

pytestmark = pytest.mark.slow


def test_octopus_latest_k3_manifest_is_backed_by_final_artifacts():
    root = Path(__file__).resolve().parents[1]
    summary = validate_manifest(root / "benchmarks/octopus-k3-latest.json")
    assert summary == {"cases": 14, "trial_passes": 42, "k": 3}
