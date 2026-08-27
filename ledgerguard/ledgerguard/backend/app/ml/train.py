from __future__ import annotations

from pathlib import Path

import joblib

from sklearn.ensemble import RandomForestClassifier


MODEL_DIR = Path("ml_models")
MODEL_PATH = (
    MODEL_DIR
    / "reconciliation_model.joblib"
)


def build_training_data():

    # 1 = records belong together
    # 0 = records do not belong together

    X = [
        # amount_diff,
        # amount_ratio,
        # order_exact,
        # order_contains,
        # fee,
        # net_gross_diff,
        # fee_ratio,
        # bank_amount_diff,
        # bank_amount_ratio,
        # bank_order_exact,
        # bank_available

        [0, 0, 1, 1, 0, 0, 0, 0, 0, 1, 1],
        [0, 0, 1, 1, 180, 180, 0.018, 0, 0, 1, 1],
        [0, 0, 1, 1, 50, 50, 0.01, 0, 0, 1, 1],
        [1, 0.0001, 1, 1, 100, 100, 0.01, 0, 0, 1, 1],

        [500, 0.05, 0, 0, 180, 180, 0.018, 0, 0, 0, 1],
        [1000, 0.10, 0, 0, 200, 200, 0.02, 1000, 0.10, 0, 1],
        [2500, 0.25, 0, 0, 500, 500, 0.05, 2500, 0.25, 0, 1],

        [0, 0, 1, 1, 180, 180, 0.018, 0, 0, 1, 1],
        [2, 0.0002, 1, 1, 180, 180, 0.018, 0, 0, 1, 1],
        [100, 0.01, 1, 1, 100, 100, 0.01, 100, 0.01, 1, 1],
    ]

    y = [
        1,
        1,
        1,
        1,
        0,
        0,
        0,
        1,
        1,
        1,
    ]

    return X, y


def train():

    MODEL_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    X, y = build_training_data()

    model = RandomForestClassifier(
        n_estimators=200,
        random_state=42,
        class_weight="balanced",
    )

    model.fit(
        X,
        y,
    )

    joblib.dump(
        model,
        MODEL_PATH,
    )

    print(
        f"MODEL SAVED: {MODEL_PATH}"
    )


if __name__ == "__main__":
    train()