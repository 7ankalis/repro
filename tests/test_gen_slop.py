"""Offline tests for scripts/gen_slop.py plan_items() (no API, no docker)."""
import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "gen_slop", Path(__file__).resolve().parent.parent / "scripts" / "gen_slop.py")
gen_slop = importlib.util.module_from_spec(_spec)
sys.modules["gen_slop"] = gen_slop  # dataclass annotation resolution needs the module registered
_spec.loader.exec_module(gen_slop)

TARGETS = [("curl", "curl"), ("arvo_42487096", "muparser")]


def test_plan_covers_all_five_modes_evenly():
    items = gen_slop.plan_items(15, TARGETS)
    assert len(items) == 15
    assert set(gen_slop.MODES) == {
        "hallucinated_function", "wrong_file", "invented_code_quote",
        "non_reproducible", "hidden_instruction_injection",
    }
    counts = {m: sum(1 for it in items if it.mode == m) for m in gen_slop.MODES}
    assert set(counts.values()) == {3}  # 15 / 5 modes = 3 each


def test_plan_ids_are_unique_and_balanced_across_targets():
    items = gen_slop.plan_items(15, TARGETS)
    rids = [it.rid for it in items]
    assert len(set(rids)) == len(rids)
    per_project = {"curl": 0, "muparser": 0}
    for it in items:
        per_project[it.project] += 1
    assert per_project == {"curl": 8, "muparser": 7}  # round-robin, curl first
    # ids are zero-padded per-project running counters
    assert "slop-curl-00" in rids and "slop-muparser-00" in rids


def test_plan_is_deterministic():
    assert gen_slop.plan_items(15, TARGETS) == gen_slop.plan_items(15, TARGETS)


def test_single_target_still_cycles_modes():
    items = gen_slop.plan_items(5, [("curl", "curl")])
    assert [it.mode for it in items] == gen_slop.MODES
    assert all(it.project == "curl" for it in items)


def test_empty_targets_raises():
    try:
        gen_slop.plan_items(3, [])
    except ValueError:
        return
    raise AssertionError("expected ValueError for empty targets")
