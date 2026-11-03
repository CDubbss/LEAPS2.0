"""Unit tests for the validation regression gate (HANDOFF §9 item A)."""

from backend.ml.validate_gate import compare


def _report(scorecard, *, fail=0, edge=188_000.0, p=0.0001, feature_nan=None, n1_z=-0.9):
    return {
        "counts": {"FAIL": fail},
        "scorecard": [{"id": i, "status": s} for i, s in scorecard],
        "sections": {
            "honest": {"H1_notional_matched": {"edge": edge, "p_value": p}},
            "invariants": {
                "I2_feature_stats": {
                    f: {"recent_nan_rate": r} for f, r in (feature_nan or {}).items()
                }
            },
            "negative_controls": {"N1_within_day_shuffle": {"z": n1_z}},
        },
    }


BASE = [("R1", "PASS"), ("H1", "PASS"), ("H3", "FAIL"), ("I2", "FAIL")]


def test_identical_reports_pass():
    base = _report(BASE, fail=2)
    assert compare(base, base).ok


def test_new_fail_is_regression():
    base = _report(BASE, fail=2)
    cur = _report([("R1", "PASS"), ("H1", "FAIL"), ("H3", "FAIL"), ("I2", "FAIL")], fail=3)
    res = compare(base, cur)
    assert not res.ok
    assert any("H1" in r for r in res.regressions)


def test_pass_to_warn_is_soft_warning_not_regression():
    base = _report(BASE, fail=2)
    cur = _report([("R1", "WARN"), ("H1", "PASS"), ("H3", "FAIL"), ("I2", "FAIL")], fail=2)
    res = compare(base, cur)
    assert res.ok  # WARN is not a hard regression
    assert any("R1" in w for w in res.warnings)


def test_edge_collapse_is_regression():
    base = _report(BASE, fail=2, edge=188_000.0)
    cur = _report(BASE, fail=2, edge=100_000.0)  # ~47% drop
    assert not compare(base, cur).ok


def test_small_edge_drift_is_ok():
    base = _report(BASE, fail=2, edge=188_000.0)
    cur = _report(BASE, fail=2, edge=170_000.0)  # ~10% drop, within tolerance
    assert compare(base, cur).ok


def test_insignificant_p_is_regression():
    base = _report(BASE, fail=2, p=0.0001)
    cur = _report(BASE, fail=2, p=0.2)
    assert not compare(base, cur).ok


def test_feature_going_nan_is_regression():
    base = _report(BASE, fail=2, feature_nan={"pe_ratio": 0.0})
    cur = _report(BASE, fail=2, feature_nan={"pe_ratio": 0.98})
    res = compare(base, cur)
    assert not res.ok
    assert any("pe_ratio" in r for r in res.regressions)


def test_negative_control_breaking_is_regression():
    base = _report(BASE, fail=2, n1_z=-0.9)
    cur = _report(BASE, fail=2, n1_z=3.5)  # harness itself now shows a spurious edge
    assert not compare(base, cur).ok
