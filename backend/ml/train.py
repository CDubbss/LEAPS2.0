"""
Training script for the XGBoost SpreadRanker model.

Usage:
    python -m backend.ml.train [--data-path ml/data/spread_outcomes.db] [--trials 50]

Requires:
    - backend/ml/data/spread_outcomes.db with at least ~500 labeled spread outcomes
    - SQLite table: spread_outcomes (features JSON + outcome_score REAL)

The scanner automatically logs candidates to this database during each scan.
After options expire, outcomes are labeled by the log_outcome.py script.
"""

import argparse
import glob
import json
import logging
import os
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import optuna
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from xgboost import XGBClassifier, XGBRegressor

from backend.ml.features import FEATURE_NAMES

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = "backend/ml/data/spread_outcomes.db"
MODEL_PATH = "backend/ml/artifacts/spread_ranker.joblib"
STRATEGY_MODEL_PATH = "backend/ml/artifacts/strategy_classifier.joblib"
SCALER_PATH = "backend/ml/artifacts/feature_scaler.joblib"

# Sample weights by label tier — expiry labels are ground truth (1.0);
# interim labels carry proportionally less weight reflecting lower signal fidelity.
# Early interim labels (5d, 10d) are heavily discounted: a 3-5 day snapshot of
# a LEAPS position is nearly noise. Weight increases as the observation window
# extends toward the full hold period.
LABEL_WEIGHTS: dict[str, float] = {
    "interim_5d":   0.05,
    "interim_10d":  0.15,
    "interim_21d":  0.25,
    "interim_30d":  0.40,
    "interim_45d":  0.50,
    "interim_60d":  0.55,
    "interim_90d":  0.60,
    "interim_180d": 0.75,
    "interim_360d": 0.85,
    "interim_540d": 0.92,
    "interim_720d": 0.96,
    "expiry":       1.00,
}


def load_training_data(db_path: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Load feature vectors, outcome scores, and sample weights from SQLite.

    Rows without a label_source (legacy rows labeled before tiering) are treated
    as expiry-weight (1.0) since they were finalized by the old pipeline.
    """
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql(
            "SELECT features_json, outcome_score, label_source "
            "FROM spread_outcomes "
            "WHERE outcome_score IS NOT NULL "
            "  AND spread_type NOT IN ('earnings_call', 'earnings_put')",
            conn,
        )
    finally:
        conn.close()

    if df.empty:
        raise ValueError("No training data found in database")

    X_list, y_list, w_list = [], [], []
    for _, row in df.iterrows():
        features = json.loads(row["features_json"])
        vec = [features.get(name, float("nan")) for name in FEATURE_NAMES]
        X_list.append(vec)
        y_list.append(float(row["outcome_score"]))
        w_list.append(LABEL_WEIGHTS.get(row["label_source"] or "expiry", 1.0))

    X = np.array(X_list, dtype=float)
    y = np.array(y_list, dtype=float)
    w = np.array(w_list, dtype=float)

    tier_dist = df["label_source"].fillna("expiry").value_counts().to_dict()
    logger.info("Loaded %d training samples | tier distribution: %s", len(y), tier_dist)
    return X, y, w


def objective(trial: optuna.Trial, X: np.ndarray, y: np.ndarray, w: np.ndarray) -> float:
    """Optuna objective: minimize weighted MSE on time-series validation split."""
    params = {
        "n_estimators": trial.suggest_int("n_estimators", 100, 500),
        "max_depth": trial.suggest_int("max_depth", 3, 7),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
        "subsample": trial.suggest_float("subsample", 0.6, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
        "reg_alpha": trial.suggest_float("reg_alpha", 1e-4, 10.0, log=True),
        "reg_lambda": trial.suggest_float("reg_lambda", 1e-4, 10.0, log=True),
        "random_state": 42,
        "tree_method": "hist",
        "device": "cpu",
    }

    tscv = TimeSeriesSplit(n_splits=5)
    mse_scores = []

    for train_idx, val_idx in tscv.split(X):
        X_train, X_val = X[train_idx], X[val_idx]
        y_train, y_val = y[train_idx], y[val_idx]
        w_train, w_val = w[train_idx], w[val_idx]

        # No scaler: trees are scale-invariant, and StandardScaler emits
        # divide warnings on all-NaN columns (regime features predate 2026-07
        # rows, so early time-series folds have 100%-NaN columns).
        pipeline = Pipeline([
            ("xgb", XGBRegressor(**params, verbosity=0)),
        ])
        pipeline.fit(X_train, y_train, xgb__sample_weight=w_train)
        preds = pipeline.predict(X_val)
        # Weighted MSE: expiry-labeled val rows penalise errors more
        mse = float(np.average((preds - y_val) ** 2, weights=w_val))
        mse_scores.append(mse)

    return float(np.mean(mse_scores))


def train(db_path: str, n_trials: int = 50) -> None:
    """Full training pipeline with Optuna hyperparameter search."""
    logger.info("Loading training data from %s", db_path)
    X, y, w = load_training_data(db_path)

    if len(y) < 100:
        logger.warning(
            "Only %d samples — results may be unreliable. "
            "Collect more data before relying on ML scores.",
            len(y),
        )

    logger.info("Running Optuna hyperparameter search (%d trials)...", n_trials)
    study = optuna.create_study(direction="minimize")
    study.optimize(
        lambda trial: objective(trial, X, y, w),
        n_trials=n_trials,
        show_progress_bar=True,
    )

    best_params = study.best_params
    logger.info("Best params: %s (weighted MSE=%.4f)", best_params, study.best_value)

    # Train final model on all data with best params and sample weights
    best_params.update({"random_state": 42, "tree_method": "hist", "device": "cpu"})
    final_pipeline = Pipeline([
        ("xgb", XGBRegressor(**best_params, verbosity=0)),
    ])
    final_pipeline.fit(X, y, xgb__sample_weight=w)

    # Save artifacts
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    joblib.dump(final_pipeline, MODEL_PATH)
    logger.info("Model saved to %s", MODEL_PATH)

    # Keep versioned copy for rollback; prune to last 3
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    versioned = MODEL_PATH.replace(".joblib", f"_{ts}.joblib")
    shutil.copy(MODEL_PATH, versioned)
    logger.info("Versioned model saved to %s", versioned)
    old_versions = sorted(glob.glob(MODEL_PATH.replace(".joblib", "_*.joblib")))[:-3]
    for old in old_versions:
        os.remove(old)
        logger.info("Pruned old model version: %s", old)

    # Save training metadata
    meta = {
        "trained_at": datetime.now(UTC).isoformat(),
        "n_samples": len(y),
        "best_weighted_mse": study.best_value,
        "best_params": best_params,
        "feature_names": FEATURE_NAMES,
        "label_weights": LABEL_WEIGHTS,
    }
    meta_path = MODEL_PATH.replace(".joblib", "_meta.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    logger.info("Training metadata saved to %s", meta_path)


def load_strategy_data(db_path: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Load features and binary win/loss labels for the strategy classifier.

    Only uses decided outcomes (win or loss) — 'open' rows are excluded.
    Sample weights use the same tier-based weighting as the ranker.
    """
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql(
            "SELECT features_json, strategy_result, label_source "
            "FROM spread_outcomes "
            "WHERE strategy_result IN ('win', 'loss') "
            "  AND features_json IS NOT NULL "
            "  AND spread_type NOT IN ('earnings_call', 'earnings_put')",
            conn,
        )
    finally:
        conn.close()

    if df.empty:
        raise ValueError("No strategy outcomes found — run label_outcomes first")

    X_list, y_list, w_list = [], [], []
    for _, row in df.iterrows():
        features = json.loads(row["features_json"])
        vec = [features.get(name, float("nan")) for name in FEATURE_NAMES]
        X_list.append(vec)
        y_list.append(1.0 if row["strategy_result"] == "win" else 0.0)
        w_list.append(LABEL_WEIGHTS.get(row["label_source"] or "expiry", 1.0))

    X = np.array(X_list, dtype=float)
    y = np.array(y_list, dtype=float)
    w = np.array(w_list, dtype=float)

    wins = int(y.sum())
    logger.info(
        "Strategy data: %d samples (%d wins, %d losses, %.1f%% win rate)",
        len(y), wins, len(y) - wins, 100 * wins / len(y),
    )
    return X, y, w


def strategy_objective(trial: optuna.Trial, X: np.ndarray, y: np.ndarray, w: np.ndarray) -> float:
    """Optuna objective for the strategy classifier: maximize AUC."""
    params = {
        "n_estimators": trial.suggest_int("n_estimators", 100, 500),
        "max_depth": trial.suggest_int("max_depth", 3, 7),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
        "subsample": trial.suggest_float("subsample", 0.6, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
        "reg_alpha": trial.suggest_float("reg_alpha", 1e-4, 10.0, log=True),
        "reg_lambda": trial.suggest_float("reg_lambda", 1e-4, 10.0, log=True),
        "scale_pos_weight": trial.suggest_float("scale_pos_weight", 0.5, 3.0),
        "random_state": 42,
        "tree_method": "hist",
        "device": "cpu",
        "eval_metric": "auc",
    }

    from sklearn.metrics import roc_auc_score
    tscv = TimeSeriesSplit(n_splits=5)
    auc_scores = []

    for train_idx, val_idx in tscv.split(X):
        X_train, X_val = X[train_idx], X[val_idx]
        y_train, y_val = y[train_idx], y[val_idx]
        w_train = w[train_idx]

        # Skip folds where either split has only one class
        if len(np.unique(y_train)) < 2 or len(np.unique(y_val)) < 2:
            continue

        pipeline = Pipeline([
            ("xgb", XGBClassifier(**params, verbosity=0, use_label_encoder=False)),
        ])
        pipeline.fit(X_train, y_train, xgb__sample_weight=w_train)
        proba = pipeline.predict_proba(X_val)[:, 1]
        auc_scores.append(roc_auc_score(y_val, proba, sample_weight=w[val_idx]))

    return -float(np.mean(auc_scores)) if auc_scores else 0.0


def train_strategy(db_path: str, n_trials: int = 50) -> None:
    """Train the strategy classifier: P(hit commission-adjusted +50% before the -50% stop)."""
    logger.info("Loading strategy data from %s", db_path)
    X, y, w = load_strategy_data(db_path)

    if len(y) < 100:
        logger.warning("Only %d strategy samples — classifier may be unreliable.", len(y))

    logger.info("Running Optuna search for strategy classifier (%d trials)...", n_trials)
    study = optuna.create_study(direction="minimize")
    study.optimize(
        lambda trial: strategy_objective(trial, X, y, w),
        n_trials=n_trials,
        show_progress_bar=True,
    )

    best_params = study.best_params
    best_auc = -study.best_value
    logger.info("Best strategy params: %s (AUC=%.4f)", best_params, best_auc)

    best_params.update({
        "random_state": 42, "tree_method": "hist", "device": "cpu",
        "eval_metric": "auc",
    })
    final_pipeline = Pipeline([
        ("xgb", XGBClassifier(**best_params, verbosity=0, use_label_encoder=False)),
    ])
    final_pipeline.fit(X, y, xgb__sample_weight=w)

    os.makedirs(os.path.dirname(STRATEGY_MODEL_PATH), exist_ok=True)
    joblib.dump(final_pipeline, STRATEGY_MODEL_PATH)
    logger.info("Strategy classifier saved to %s", STRATEGY_MODEL_PATH)

    wins = int(y.sum())
    meta = {
        "trained_at": datetime.now(UTC).isoformat(),
        "n_samples": len(y),
        "n_wins": wins,
        "n_losses": len(y) - wins,
        "win_rate": round(wins / len(y), 4),
        "best_auc": round(best_auc, 4),
        "best_params": best_params,
        "profit_target_pct": 50.0,
        "stop_loss_pct": -50.0,
        "commission_per_10_contracts": 26.0,
        "feature_names": FEATURE_NAMES,
    }
    meta_path = STRATEGY_MODEL_PATH.replace(".joblib", "_meta.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    logger.info("Strategy metadata saved to %s", meta_path)


def init_database(db_path: str) -> None:
    """Create the spread outcomes database if it doesn't exist."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS spread_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id TEXT,
            symbol TEXT,
            spread_type TEXT,
            expiration TEXT,
            entry_date TEXT,
            outcome_score REAL,        -- 0-100 label (set after expiry)
            features_json TEXT,        -- JSON of FeatureVector
            logged_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    logger.info("Database initialized at %s", db_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train SpreadRanker ML model")
    parser.add_argument("--data-path", default=DB_PATH)
    parser.add_argument("--trials", type=int, default=50)
    parser.add_argument("--init-db", action="store_true", help="Initialize database only")
    args = parser.parse_args()

    if args.init_db:
        init_database(args.data_path)
    else:
        train(args.data_path, args.trials)
        try:
            train_strategy(args.data_path, args.trials)
        except ValueError as e:
            logger.warning("Skipping strategy classifier: %s", e)
