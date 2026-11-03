"""Tests for the NYSE-expansion tier isolation scaffolding (Phase 1).

Covers the three invariants that keep the expansion tier from touching the core
LEAPS model:
  - the expansion universe is a registered, DISJOINT group (never folded into
    DEFAULT_UNIVERSE);
  - OutcomeLogger is tier-tagged and self-sufficient on a fresh DB (so the first
    expansion scan can't crash on a missing column);
  - OptionsScanner routes writes through an injected OutcomeLogger.
"""

import sqlite3

from backend.ml.outcome_logger import OutcomeLogger
from backend.scanner import universe as U


def _cols(db_path: str) -> set[str]:
    con = sqlite3.connect(db_path)
    try:
        return {r[1] for r in con.execute("PRAGMA table_info(spread_outcomes)")}
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# Universe isolation
# --------------------------------------------------------------------------- #

def test_nyse_expansion_group_registered():
    assert "nyse_expansion" in U.UNIVERSE_GROUPS
    assert U.UNIVERSE_GROUPS["nyse_expansion"] is U._NYSE_EXPANSION


def test_expansion_is_disjoint_from_core():
    # The whole point of the tier: an expansion name must never already live in
    # the core universe (that would reintroduce the distribution it isolates).
    overlap = set(U._NYSE_EXPANSION) & set(U.DEFAULT_UNIVERSE)
    assert not overlap, f"expansion overlaps core: {sorted(overlap)}"


def test_core_plus_expansion_is_the_union():
    cpe = U.core_plus_expansion()
    assert set(U.DEFAULT_UNIVERSE) <= set(cpe)
    assert set(U._NYSE_EXPANSION) <= set(cpe)
    assert cpe == sorted(set(U.DEFAULT_UNIVERSE) | set(U._NYSE_EXPANSION))
    # Core universe itself is untouched by the new tier.
    assert "AAPL" in U.DEFAULT_UNIVERSE


# --------------------------------------------------------------------------- #
# OutcomeLogger — tier tag + fresh-DB self-sufficiency
# --------------------------------------------------------------------------- #

def test_fresh_db_has_every_column_the_insert_writes(tmp_path):
    # A brand-new NYSE DB is created by OutcomeLogger alone (no label_outcomes
    # migration has run), so every column the INSERT references must be present
    # or the first expansion scan crashes.
    db = str(tmp_path / "spread_outcomes_nyse.db")
    OutcomeLogger(db_path=db, universe_tier="nyse_expansion")
    cols = _cols(db)
    for c in ("universe_tier", "market_closed", "near_miss",
              "entry_net_debit", "features_json", "contract_json"):
        assert c in cols, f"missing column on fresh DB: {c}"


def test_logger_tier_defaults_to_core(tmp_path):
    db = str(tmp_path / "spread_outcomes.db")
    lg = OutcomeLogger(db_path=db)
    assert lg.universe_tier == "core"


def test_logger_tier_can_be_expansion(tmp_path):
    lg = OutcomeLogger(db_path=str(tmp_path / "x.db"), universe_tier="nyse_expansion")
    assert lg.universe_tier == "nyse_expansion"


# --------------------------------------------------------------------------- #
# OptionsScanner injection
# --------------------------------------------------------------------------- #

def test_scanner_uses_injected_outcome_logger(tmp_path):
    # Passing an explicit logger short-circuits the default OutcomeLogger() (which
    # would otherwise open the real core DB), so this construction is side-effect
    # free against a temp DB.
    from backend.scanner.scanner import OptionsScanner

    lg = OutcomeLogger(db_path=str(tmp_path / "inj.db"), universe_tier="nyse_expansion")
    scanner = OptionsScanner(
        yf_client=None,
        fmp_client=None,
        news_aggregator=None,
        sentiment_scorer=None,
        sentiment_aggregator=None,
        ml_ranker=None,
        cache=None,
        outcome_logger=lg,
    )
    assert scanner.outcome_logger is lg
    assert scanner.outcome_logger.universe_tier == "nyse_expansion"


# --------------------------------------------------------------------------- #
# Scheduled-scan tier routing (the isolation seam)
# --------------------------------------------------------------------------- #

def test_resolve_tier_routes_expansion_to_separate_paths():
    from backend.config.settings import get_settings
    from backend.scripts.scheduled_scan import _resolve_tier

    settings = get_settings()

    tier, model, db = _resolve_tier("nyse_expansion", settings)
    assert tier == "nyse_expansion"
    assert model == settings.ML_MODEL_PATH_NYSE
    assert db == settings.SPREAD_OUTCOMES_DB_NYSE

    # Core (and any unknown tier) must stay on the core model + DB.
    for name in ("core", "", "something_else"):
        tier, model, db = _resolve_tier(name, settings)
        assert tier == "core"
        assert model == settings.ML_MODEL_PATH
        assert db == settings.SPREAD_OUTCOMES_DB

    # The two tiers must never share a DB or an artifact.
    assert settings.SPREAD_OUTCOMES_DB != settings.SPREAD_OUTCOMES_DB_NYSE
    assert settings.ML_MODEL_PATH != settings.ML_MODEL_PATH_NYSE


# --------------------------------------------------------------------------- #
# Combined read — review / joint model over both tiers (forward-compat)
# --------------------------------------------------------------------------- #

def _seed_db(path: str, tier: str, n: int, score: float = 50.0) -> None:
    """Create a schema-identical outcomes DB and insert n decided rows."""
    OutcomeLogger(db_path=path, universe_tier=tier)  # creates the schema
    con = sqlite3.connect(path)
    try:
        con.executemany(
            "INSERT INTO spread_outcomes (symbol, spread_type, outcome_score, "
            "features_json, label_source, market_closed, universe_tier, strategy_result) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(f"{tier[:3].upper()}{i}", "leap_call", score, "{}", "expiry", 0, tier, "win")
             for i in range(n)],
        )
        con.commit()
    finally:
        con.close()


def test_read_outcomes_unions_schema_identical_dbs(tmp_path):
    from backend.ml.train import _read_outcomes, load_training_data

    core_db = str(tmp_path / "spread_outcomes.db")
    nyse_db = str(tmp_path / "spread_outcomes_nyse.db")
    _seed_db(core_db, "core", n=3)
    _seed_db(nyse_db, "nyse_expansion", n=2)

    # Single-DB reads unchanged.
    assert len(_read_outcomes(core_db, "SELECT outcome_score FROM spread_outcomes")) == 3

    # Passing a list UNIONs both tiers (the combined-review / joint-model path),
    # and universe_tier is available to segment by.
    both = _read_outcomes(
        [core_db, nyse_db],
        "SELECT outcome_score, universe_tier FROM spread_outcomes",
    )
    assert len(both) == 5
    assert set(both["universe_tier"]) == {"core", "nyse_expansion"}

    # The trainer's loader accepts the same list and trains over the union.
    _, y, _ = load_training_data([core_db, nyse_db])
    assert len(y) == 5


def test_load_training_data_single_path_unchanged(tmp_path):
    from backend.ml.train import load_training_data

    core_db = str(tmp_path / "spread_outcomes.db")
    _seed_db(core_db, "core", n=4)
    _, y, _ = load_training_data(core_db)
    assert len(y) == 4
