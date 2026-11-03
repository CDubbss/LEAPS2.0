"""Tests for the automated Ted track record (backend/ml/ted_outcomes.py)."""

from datetime import date, timedelta

from backend.ml import ted_outcomes as to

TODAY = date(2026, 10, 30)


def _payload(**over):
    c = {
        "symbol": "AAPL",
        "earnings_date": "2026-11-11",
        "exit_by": "2026-11-11",
        "qualifying_expiry": "2026-11-13",
        "option_side": "call",
        "inferred_direction": "bull",
        "atm_strike": 100.0,
        "entry_iv": 40.0,
        "entry_price": 1.10,
        "iv_room": True,
        "big_mover_count": 4,
        "attention": True,
        "prescreen_score": 4,
        "qualifies": True,
    }
    c.update(over)
    return {"candidates": [c]}


def test_log_only_qualifiers(tmp_path):
    db = tmp_path / "ted.db"
    payload = {"candidates": [
        _payload()["candidates"][0],
        {"symbol": "FOO", "earnings_date": "2026-11-10", "qualifies": False},
    ]}
    assert to.log_candidates(payload, db) == 1
    s = to.summary(db)
    assert s["total"] == 1 and s["open"] == 1 and s["labeled"] == 0


def test_upsert_no_duplicate(tmp_path):
    db = tmp_path / "ted.db"
    to.log_candidates(_payload(entry_iv=40.0), db)
    to.log_candidates(_payload(entry_iv=45.0), db)  # same symbol+earnings → update, not dup
    s = to.summary(db)
    assert s["total"] == 1


def test_due_for_label_respects_exit_by(tmp_path):
    db = tmp_path / "ted.db"
    to.log_candidates(_payload(earnings_date="2026-11-11", exit_by="2026-11-11"), db)   # future
    to.log_candidates(_payload(symbol="MSFT", earnings_date="2026-10-20",
                               exit_by="2026-10-20"), db)                                # past
    due = to.due_for_label(db, today=TODAY)
    assert [r["symbol"] for r in due] == ["MSFT"]


def test_record_outcome_computes_iv_change(tmp_path):
    db = tmp_path / "ted.db"
    to.log_candidates(_payload(symbol="MSFT", earnings_date="2026-10-20",
                               exit_by="2026-10-20", entry_iv=35.0), db)
    row = to.due_for_label(db, today=TODAY)[0]
    to.record_outcome(row["id"], exit_iv=48.0, exit_price=1.5, db_path=db)
    s = to.summary(db)
    assert s["labeled"] == 1 and s["open"] == 0
    assert s["avg_iv_change"] == 13.0 and s["iv_up"] == 1   # 48 - 35 = +13 (IV built)
    # labeled rows are no longer due
    assert to.due_for_label(db, today=TODAY) == []
