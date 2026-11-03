"""Regression gate over validate.py's output (HANDOFF §9 item A).

Every costly bug in this project (era contamination §4.1, clamped snapshots
§4.7, weekend scans §4.8) hid inside a healthy-looking aggregate and was only
caught by *splitting* that aggregate. `validate.py` already does the splitting;
this turns it into a standing guard: after each validation run, diff the new
scorecard against a saved baseline and FAIL (exit 3) on any regression.

Design notes
------------
- Read-only and side-effect-free except for writing the baseline on
  ``--update-baseline``. It never touches the outcomes DB.
- Operates on the artifact JSON that ``validate.py --json`` already writes, so
  it stays decoupled and fast. ``--run`` will invoke ``validate.py`` first.
- Thresholds are declared up top (mirroring validate.py's convention) and
  printed before any verdict, so loosening one shows up in ``git diff``.

Intended wiring (not auto-scheduled here)::

    backend\\.venv\\Scripts\\python.exe -m backend.ml.validate --json
    backend\\.venv\\Scripts\\python.exe -m backend.ml.validate_gate   # exit 3 on regression

Run once with ``--update-baseline`` to seed the baseline from a run you trust.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# UTF-8 guard — same cp1252 hazard as the other CLI entry points (HANDOFF §6).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

ARTIFACTS = Path("backend/ml/artifacts")
REPORT_PATH = ARTIFACTS / "validation_report.json"
BASELINE_PATH = ARTIFACTS / "validation_baseline.json"

# --- Regression thresholds (printed before any verdict) --------------------- #
THRESHOLDS = {
    # The notional-matched selection edge is the load-bearing validated claim.
    # Flag a drop of more than this fraction vs the baseline.
    "edge_drop_frac": 0.25,
    # H1 p-value must stay significant.
    "max_p_value": 0.05,
    # A feature's recent NaN rate rising by more than this (absolute) is the
    # §4.9 / I2 silent-death signature.
    "feature_nan_rate_increase": 0.20,
    # Negative control N1 must keep showing no edge.
    "control_max_abs_z": 2.0,
}

# A check moving *into* one of these states (from a better one) is a hard
# regression. PASS > WARN/INFO > FAIL.
_RANK = {"PASS": 3, "INFO": 2, "WARN": 1, "FAIL": 0}


@dataclass
class GateResult:
    regressions: list[str] = field(default_factory=list)  # hard — exit non-zero
    warnings: list[str] = field(default_factory=list)      # soft — reported only
    notes: list[str] = field(default_factory=list)         # informational

    @property
    def ok(self) -> bool:
        return not self.regressions


def _scorecard_status(report: dict) -> dict[str, str]:
    return {c["id"]: c.get("status", "?") for c in report.get("scorecard", [])}


def _h1(report: dict) -> dict:
    return (
        report.get("sections", {})
        .get("honest", {})
        .get("H1_notional_matched", {})
    )


def _feature_nan(report: dict) -> dict[str, float]:
    stats = (
        report.get("sections", {})
        .get("invariants", {})
        .get("I2_feature_stats", {})
    )
    out: dict[str, float] = {}
    for feat, s in stats.items():
        if isinstance(s, dict) and s.get("recent_nan_rate") is not None:
            out[feat] = float(s["recent_nan_rate"])
    return out


def _n1_abs_z(report: dict) -> float | None:
    n1 = (
        report.get("sections", {})
        .get("negative_controls", {})
        .get("N1_within_day_shuffle", {})
    )
    z = n1.get("z")
    return abs(float(z)) if z is not None else None


def compare(baseline: dict, current: dict, thresholds: dict[str, Any] = THRESHOLDS) -> GateResult:
    """Pure comparison — no I/O — so it is unit-testable."""
    res = GateResult()

    # 1. Per-check status regressions.
    base_status = _scorecard_status(baseline)
    cur_status = _scorecard_status(current)
    for check_id, cur in cur_status.items():
        base = base_status.get(check_id)
        if base is None:
            res.notes.append(f"{check_id}: new check ({cur})")
            continue
        if _RANK.get(cur, 0) < _RANK.get(base, 0):
            msg = f"{check_id}: {base} -> {cur}"
            if cur == "FAIL":
                res.regressions.append(msg)
            else:
                res.warnings.append(msg)
    for check_id in base_status:
        if check_id not in cur_status:
            res.warnings.append(f"{check_id}: present in baseline, missing now")

    # 2. Scorecard FAIL count must not grow.
    bc, cc = baseline.get("counts", {}), current.get("counts", {})
    if cc.get("FAIL", 0) > bc.get("FAIL", 0):
        res.regressions.append(
            f"FAIL count {bc.get('FAIL', 0)} -> {cc.get('FAIL', 0)}"
        )

    # 3. Selection edge must not collapse, and must stay significant.
    b_edge = _h1(baseline).get("edge")
    c_edge = _h1(current).get("edge")
    if b_edge and c_edge is not None and b_edge > 0:
        drop = (b_edge - c_edge) / b_edge
        if drop > thresholds["edge_drop_frac"]:
            res.regressions.append(
                f"notional-matched edge dropped {drop:.0%}: "
                f"${b_edge:,.0f} -> ${c_edge:,.0f}"
            )
    c_p = _h1(current).get("p_value")
    if c_p is not None and c_p > thresholds["max_p_value"]:
        res.regressions.append(
            f"edge no longer significant: p={c_p} > {thresholds['max_p_value']}"
        )

    # 4. Silent feature death (§4.9 / I2).
    b_nan, c_nan = _feature_nan(baseline), _feature_nan(current)
    for feat, c_rate in c_nan.items():
        b_rate = b_nan.get(feat)
        if b_rate is None:
            continue
        if c_rate - b_rate > thresholds["feature_nan_rate_increase"]:
            res.regressions.append(
                f"feature '{feat}' recent NaN rate {b_rate:.0%} -> {c_rate:.0%}"
            )

    # 5. Negative control must stay clean (else the harness itself broke).
    c_z = _n1_abs_z(current)
    if c_z is not None and c_z > thresholds["control_max_abs_z"]:
        res.regressions.append(
            f"N1 within-day shuffle shows edge: |z|={c_z:.2f} "
            f"> {thresholds['control_max_abs_z']}"
        )

    return res


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="run validate.py --json first")
    ap.add_argument("--slow", action="store_true", help="with --run, pass --slow to validate.py")
    ap.add_argument("--update-baseline", action="store_true",
                    help="overwrite the baseline with the current report and exit 0")
    ap.add_argument("--report", default=str(REPORT_PATH))
    ap.add_argument("--baseline", default=str(BASELINE_PATH))
    args = ap.parse_args()

    if args.run:
        cmd = [sys.executable, "-m", "backend.ml.validate", "--json"]
        if args.slow:
            cmd.append("--slow")
        print("Running:", " ".join(cmd))
        # validate.py exits non-zero when FAILs exist; that is expected, so we
        # do not treat its exit code as the gate verdict — the report does.
        subprocess.run(cmd, check=False)

    report_path, baseline_path = Path(args.report), Path(args.baseline)
    if not report_path.exists():
        print(f"ERROR: no validation report at {report_path} (run validate.py --json first)")
        return 2
    current = _load(report_path)

    if args.update_baseline or not baseline_path.exists():
        baseline_path.write_text(json.dumps(current, indent=2), encoding="utf-8")
        action = "updated" if args.update_baseline else "seeded (no baseline existed)"
        print(f"Baseline {action}: {baseline_path}")
        print(f"  scorecard: {current.get('counts')}")
        print(f"  generated_at: {current.get('generated_at')}")
        return 0

    baseline = _load(baseline_path)
    print("Gate thresholds:", json.dumps(THRESHOLDS))
    print(f"Baseline generated_at: {baseline.get('generated_at')}")
    print(f"Current  generated_at: {current.get('generated_at')}")
    print("-" * 60)

    res = compare(baseline, current)
    for n in res.notes:
        print(f"  [note] {n}")
    for w in res.warnings:
        print(f"  [warn] {w}")
    for r in res.regressions:
        print(f"  [REGRESSION] {r}")
    print("-" * 60)

    if res.ok:
        print("GATE PASS — no regressions vs baseline.")
        return 0
    print(f"GATE FAIL — {len(res.regressions)} regression(s) vs baseline.")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
