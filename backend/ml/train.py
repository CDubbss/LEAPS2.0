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
import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import optuna
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

from backend.ml.features import FEATURE_NAMES

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = "backend/ml/data/spread_outcomes.db"
MODEL_PATH = "backend/ml/artifacts/spread_ranker.joblib"
SCALER_PATH = "backend/ml/artifacts/feature_scaler.joblib"


def load_training_data(db_path: str) -> tuple[np.ndarray, np.ndarray]:
    """Load feature vectors and outcome scores from SQLite."""
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql("SELECT features_json, outcome_score FROM spread_outcomes", conn)
    finally:
        conn.close()

    if df.empty:
        raise ValueError("No training data found in database")

    X_list = []
    y_list = []
    for _, row in df.iterrows():
        features = json.loads(row["features_json"])
        vec = [features.get(name, 0.0) for name in FEATURE_NAMES]
        X_list.append(vec)
        y_list.append(float(row["outcome_score"]))

    X = np.array(X_list, dtype=float)
    y = np.array(y_list, dtype=float)
    logger.info("Loaded %d training samples", len(y))
    return X, y


def objective(trial: optuna.Trial, X: np.ndarray, y: np.ndarray) -> float:
    """Optuna objective: minimize MSE on time-series validation split."""
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

        pipeline = Pipeline([
            ("scaler", StandardScaler()),
            ("xgb", XGBRegressor(**params, verbosity=0)),
        ])
        pipeline.fit(X_train, y_train)
        preds = pipeline.predict(X_val)
        mse = float(np.mean((preds - y_val) ** 2))
        mse_scores.append(mse)

    return float(np.mean(mse_scores))


def train(db_path: str, n_trials: int = 50) -> None:
    """Full training pipeline with Optuna hyperparameter search."""
    logger.info("Loading training data from %s", db_path)
    X, y = load_training_data(db_path)

    if len(y) < 100:
        logger.warning(
            "Only %d samples — results may be unreliable. "
            "Collect more data before relying on ML scores.",
            len(y),
        )

    logger.info("Running Optuna hyperparameter search (%d trials)...", n_trials)
    study = optuna.create_study(direction="minimize")
    study.optimize(lambda trial: objective(trial, X, y), n_trials=n_trials, show_progress_bar=True)

    best_params = study.best_params
    logger.info("Best params: %s (MSE=%.4f)", best_params, study.best_value)

    # Train final model on all data with best params
    best_params.update({"random_state": 42, "tree_method": "hist", "device": "cpu"})
    final_pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("xgb", XGBRegressor(**best_params, verbosity=0)),
    ])
    final_pipeline.fit(X, y)

    # Save artifacts
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    joblib.dump(final_pipeline, MODEL_PATH)
    logger.info("Model saved to %s", MODEL_PATH)

    # Save training metadata
    meta = {
        "trained_at": datetime.utcnow().isoformat(),
        "n_samples": len(y),
        "best_mse": study.best_value,
        "best_params": best_params,
        "feature_names": FEATURE_NAMES,
    }
    meta_path = MODEL_PATH.replace(".joblib", "_meta.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    logger.info("Training metadata saved to %s", meta_path)


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
