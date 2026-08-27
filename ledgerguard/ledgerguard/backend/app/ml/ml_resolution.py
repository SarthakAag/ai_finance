from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib


class MLResolutionError(Exception):
    pass


class MLResolver:

    def __init__(
        self,
        model_path: str = "ml_models/reconciliation_model.joblib",
    ):
        self.model_path = Path(model_path)
        self.model = None

        if self.model_path.exists():
            self.model = joblib.load(
                self.model_path
            )

    @property
    def is_ready(self) -> bool:
        return self.model is not None

    def predict(
        self,
        features: dict[str, float],
    ) -> dict[str, Any]:

        if not self.is_ready:

            return {
                "ready": False,
                "prediction": None,
                "confidence": 0.0,
                "decision": "AI_REVIEW",
                "message": (
                    "ML model is not trained yet."
                ),
            }

        vector = [
            list(features.values())
        ]

        prediction = int(
            self.model.predict(vector)[0]
        )

        probabilities = (
            self.model.predict_proba(vector)[0]
        )

        confidence = float(
            max(probabilities)
        )

        # --------------------------------------------------
        # IMPORTANT:
        # Confidence alone must NEVER trigger resolution.
        #
        # Only prediction=1 means the model believes the
        # records are a valid reconciliation match.
        # --------------------------------------------------

        if (
            prediction == 1
            and confidence >= 0.90
        ):

            decision = "AUTO_RESOLVE"

        elif (
            prediction == 1
            and confidence >= 0.60
        ):

            decision = "AI_REVIEW"

        elif prediction == 0:

            # The model believes this is NOT a match.
            # Never automatically resolve it.
            decision = "HUMAN_REVIEW"

        else:

            decision = "HUMAN_REVIEW"

        return {
            "ready": True,
            "prediction": prediction,
            "confidence": round(
                confidence,
                4,
            ),
            "decision": decision,
        }