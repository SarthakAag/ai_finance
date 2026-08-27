from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    BankCredit,
    GatewaySettlement,
    ReconciliationMatch,
    SalesInvoice,
    MatchStatus,
)

from app.reconciliation.engine import ReconciliationEngine
from app.reconciliation.candidates import find_invoice_candidates
from app.ml.feature_engineering import build_match_features
from app.ml.ml_resolution import MLResolver


class ReconciliationService:
    """
    Main reconciliation service.

    Flow:

        Gateway
           |
           v
        Exact Order ID
           |
        +--+----------------+
        |                   |
      Found              Not Found
        |                   |
        v                   v
    Deterministic       Candidate Search
        |                   |
        |                   v
        |                  ML
        |                   |
        |          +--------+--------+
        |          |        |        |
        |        Auto     AI       Human
        |        Resolve  Review   Review
        |                   |
        |                   v
        |                Agent
        |                   |
        |             +-----+-----+
        |             |           |
        |          Resolved    Escalated
        |
        v
      Match
    """

    AUTO_RESOLVE_THRESHOLD = 0.90
    AI_REVIEW_THRESHOLD = 0.55
    AMBIGUITY_GAP = 0.10

    def __init__(self, db: Session):
        self.db = db
        self.engine = ReconciliationEngine()
        self.ml_resolver = MLResolver()

    # =========================================================
    # GATEWAY -> INVOICE
    # =========================================================

    def reconcile_gateway_settlement(
        self,
        gateway: GatewaySettlement,
    ) -> dict[str, Any]:

        # -----------------------------------------------------
        # STEP 1
        # Try exact order-ID lookup first.
        # -----------------------------------------------------

        invoice = None

        if gateway.order_id:

            invoice = (
                self.db.query(SalesInvoice)
                .filter(
                    SalesInvoice.order_id
                    == gateway.order_id
                )
                .first()
            )

        # -----------------------------------------------------
        # STEP 2
        # If order ID lookup fails, find candidates.
        # -----------------------------------------------------

        if invoice is None:

            candidates = find_invoice_candidates(
                self.db,
                gateway,
                limit=10,
            )

            if not candidates:

                return {
                    "matched": False,
                    "stage": "candidate_not_found",
                    "confidence": 0.0,
                    "decision": "HUMAN_REVIEW",
                    "resolver": "candidate_search",
                    "reason": (
                        "No suitable invoice candidates "
                        "were found."
                    ),
                    "order_id": gateway.order_id,
                    "settlement_id": gateway.settlement_id,
                }

            # -------------------------------------------------
            # IMPORTANT:
            #
            # Never blindly select candidates[0].
            #
            # Every candidate must be evaluated.
            # -------------------------------------------------

            return self._evaluate_candidates_with_ml(
                gateway=gateway,
                candidates=candidates,
            )

        # -----------------------------------------------------
        # STEP 3
        # Deterministic reconciliation.
        # -----------------------------------------------------

        result = self.engine.reconcile_invoice_gateway(
            invoice,
            gateway,
        )

        if result.matched:

            match = ReconciliationMatch(
                order_id=(
                    gateway.order_id
                    or invoice.order_id
                ),
                sales_invoice_id=invoice.id,
                gateway_settlement_id=gateway.id,
                status=MatchStatus.RECONCILED,
                match_stage=result.stage,
                variance_amount=result.variance_amount,
                variance_reason=result.variance_reason,
                confidence=str(
                    result.confidence
                ),
            )

            self.db.add(match)
            self.db.commit()
            self.db.refresh(match)

            return {
                "matched": True,
                "stage": result.stage,
                "confidence": result.confidence,
                "variance_amount": result.variance_amount,
                "variance_reason": result.variance_reason,
                "explanation": result.explanation,
                "match_id": match.id,
                "order_id": (
                    gateway.order_id
                    or invoice.order_id
                ),
                "settlement_id": gateway.settlement_id,
                "resolver": "deterministic",
            }

        # -----------------------------------------------------
        # STEP 4
        # Deterministic reconciliation failed.
        # Use ML.
        # -----------------------------------------------------

        return self._run_ml_fallback(
            gateway=gateway,
            invoice=invoice,
            bank=None,
        )

    # =========================================================
    # CANDIDATE -> ML
    # =========================================================

    def _evaluate_candidates_with_ml(
        self,
        gateway: GatewaySettlement,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:

        candidate_results: list[dict[str, Any]] = []

        # -----------------------------------------------------
        # Evaluate every candidate.
        # -----------------------------------------------------

        for candidate in candidates:

            invoice = candidate["invoice"]

            features = build_match_features(
                invoice=invoice,
                gateway=gateway,
                bank=None,
            )

            prediction = self.ml_resolver.predict(
                features
            )

            candidate_results.append(
                {
                    "invoice": invoice,
                    "candidate_score": float(
                        candidate.get(
                            "score",
                            0.0,
                        )
                    ),
                    "amount_difference": float(
                        candidate.get(
                            "amount_difference",
                            0.0,
                        )
                    ),
                    "amount_ratio": float(
                        candidate.get(
                            "amount_ratio",
                            0.0,
                        )
                    ),
                    "features": features,
                    "prediction": prediction,
                }
            )

        if not candidate_results:

            return {
                "matched": False,
                "stage": "candidate_not_found",
                "confidence": 0.0,
                "decision": "HUMAN_REVIEW",
                "resolver": "candidate_search",
                "order_id": gateway.order_id,
                "settlement_id": gateway.settlement_id,
                "reason": "No candidates available.",
                "candidates": [],
            }

        # -----------------------------------------------------
        # Separate predictions.
        # -----------------------------------------------------

        positive_candidates = [
            candidate
            for candidate in candidate_results
            if candidate["prediction"].get(
                "prediction"
            ) == 1
        ]

        # -----------------------------------------------------
        # Sort ALL candidates by:
        #
        # 1. ML confidence
        # 2. candidate score
        # 3. amount difference
        #
        # This is important for AI review.
        # Even when ML predicts 0, we still need the strongest
        # evidence candidate available to the agent.
        # -----------------------------------------------------

        ranked_candidates = sorted(
            candidate_results,
            key=lambda candidate: (
                float(
                    candidate["prediction"].get(
                        "confidence",
                        0.0,
                    )
                ),
                float(
                    candidate["candidate_score"]
                ),
                -float(
                    candidate["amount_difference"]
                ),
            ),
            reverse=True,
        )

        # -----------------------------------------------------
        # If there are positive ML candidates, prioritize them.
        # -----------------------------------------------------

        if positive_candidates:

            ranked_positive = sorted(
                positive_candidates,
                key=lambda candidate: (
                    float(
                        candidate["prediction"].get(
                            "confidence",
                            0.0,
                        )
                    ),
                    float(
                        candidate["candidate_score"]
                    ),
                    -float(
                        candidate["amount_difference"]
                    ),
                ),
                reverse=True,
            )

            best = ranked_positive[0]

        else:

            # -------------------------------------------------
            # No positive ML prediction.
            #
            # Do NOT immediately discard the candidates.
            #
            # A candidate with strong deterministic evidence
            # should be available for AI investigation.
            # -------------------------------------------------

            best = ranked_candidates[0]

        best_prediction = best["prediction"]

        best_confidence = float(
            best_prediction.get(
                "confidence",
                0.0,
            )
        )

        best_decision = best_prediction.get(
            "decision",
            "HUMAN_REVIEW",
        )

        best_prediction_value = (
            best_prediction.get(
                "prediction"
            )
        )

        # =====================================================
        # SAFETY CHECK
        # =====================================================

        # Only compare candidates that ML considered positive.
        #
        # If multiple candidates are almost equally confident,
        # do not automatically select one.

        if len(positive_candidates) > 1:

            positive_candidates_sorted = sorted(
                positive_candidates,
                key=lambda candidate: (
                    float(
                        candidate["prediction"].get(
                            "confidence",
                            0.0,
                        )
                    ),
                    float(
                        candidate["candidate_score"]
                    ),
                ),
                reverse=True,
            )

            first = positive_candidates_sorted[0]
            second = positive_candidates_sorted[1]

            first_confidence = float(
                first["prediction"].get(
                    "confidence",
                    0.0,
                )
            )

            second_confidence = float(
                second["prediction"].get(
                    "confidence",
                    0.0,
                )
            )

            confidence_gap = (
                first_confidence
                - second_confidence
            )

            if (
                first_confidence
                >= self.AUTO_RESOLVE_THRESHOLD
                and confidence_gap
                < self.AMBIGUITY_GAP
            ):

                return self._create_human_review_response(
                    gateway=gateway,
                    candidate_results=candidate_results,
                    confidence=first_confidence,
                    reason=(
                        "Multiple invoice candidates "
                        "received similar ML confidence. "
                        "Automatic resolution is blocked."
                    ),
                    stage="ml_ambiguous",
                )

        # =====================================================
        # AUTO RESOLVE
        # =====================================================

        if (
            best_prediction_value == 1
            and best_decision == "AUTO_RESOLVE"
            and best_confidence
            >= self.AUTO_RESOLVE_THRESHOLD
        ):

            invoice = best["invoice"]

            match = ReconciliationMatch(
                order_id=(
                    gateway.order_id
                    or invoice.order_id
                ),
                sales_invoice_id=invoice.id,
                gateway_settlement_id=gateway.id,
                status=MatchStatus.RECONCILED,
                match_stage="ml",
                variance_amount=round(
                    (
                        gateway.gross_amount
                        or 0
                    )
                    - (
                        invoice.amount
                        or 0
                    ),
                    2,
                ),
                variance_reason="ml_match",
                confidence=str(
                    best_confidence
                ),
            )

            self.db.add(match)
            self.db.commit()
            self.db.refresh(match)

            return {
                "matched": True,
                "stage": "ml",
                "confidence": best_confidence,
                "decision": "AUTO_RESOLVE",
                "resolver": "ml",
                "match_id": match.id,
                "order_id": (
                    gateway.order_id
                    or invoice.order_id
                ),
                "settlement_id": gateway.settlement_id,
                "selected_invoice": invoice.invoice_id,
                "features": best["features"],
                "candidates": (
                    self._serialize_candidates(
                        candidate_results
                    )
                ),
            }

        # =====================================================
        # AI REVIEW
        # =====================================================

        # AI review can happen in two situations:
        #
        # 1. ML explicitly says AI_REVIEW.
        #
        # 2. ML says prediction=0 but there is still a credible
        #    candidate that should be investigated.
        #
        # This prevents uncertain cases from being thrown
        # directly into human review.

        should_ai_review = False

        if best_decision == "AI_REVIEW":

            should_ai_review = True

        elif (
            best_prediction_value == 0
            and self._candidate_has_reasonable_evidence(
                best
            )
        ):

            should_ai_review = True

        elif (
            best_confidence
            >= self.AI_REVIEW_THRESHOLD
        ):

            should_ai_review = True

        if should_ai_review:

            invoice = best["invoice"]

            match = ReconciliationMatch(
                order_id=(
                    gateway.order_id
                    or invoice.order_id
                    or gateway.order_id
                ),
                sales_invoice_id=invoice.id,
                gateway_settlement_id=gateway.id,
                status=MatchStatus.PENDING,
                match_stage="ml_ai_review",
                variance_amount=round(
                    (
                        gateway.gross_amount
                        or 0
                    )
                    - (
                        invoice.amount
                        or 0
                    ),
                    2,
                ),
                variance_reason="ml_uncertain",
                confidence=str(
                    best_confidence
                ),
            )

            self.db.add(match)
            self.db.commit()
            self.db.refresh(match)

            return {
                "matched": False,
                "stage": "ml",
                "confidence": best_confidence,
                "decision": "AI_REVIEW",
                "resolver": "ml",
                "match_id": match.id,
                "order_id": (
                    gateway.order_id
                    or invoice.order_id
                ),
                "settlement_id": gateway.settlement_id,
                "selected_invoice": invoice.invoice_id,
                "features": best["features"],
                "reason": (
                    "ML identified a potentially relevant "
                    "candidate but could not safely resolve "
                    "the reconciliation automatically. "
                    "AI investigation is required."
                ),
                "candidates": (
                    self._serialize_candidates(
                        candidate_results
                    )
                ),
            }

        # =====================================================
        # HUMAN REVIEW
        # =====================================================

        return self._create_human_review_response(
            gateway=gateway,
            candidate_results=candidate_results,
            confidence=best_confidence,
            reason=(
                "ML could not identify a sufficiently "
                "credible candidate for AI investigation."
            ),
            stage="ml",
        )

    # =========================================================
    # CANDIDATE EVIDENCE CHECK
    # =========================================================

    @staticmethod
    def _candidate_has_reasonable_evidence(
        candidate: dict[str, Any],
    ) -> bool:

        candidate_score = float(
            candidate.get(
                "candidate_score",
                0.0,
            )
        )

        amount_difference = abs(
            float(
                candidate.get(
                    "amount_difference",
                    999999999,
                )
            )
        )

        amount_ratio = abs(
            float(
                candidate.get(
                    "amount_ratio",
                    999999999,
                )
            )
        )

        prediction = candidate.get(
            "prediction",
            {},
        )

        confidence = float(
            prediction.get(
                "confidence",
                0.0,
            )
        )

        # Strong candidate score.
        if candidate_score >= 0.30:

            return True

        # Very close monetary amount.
        if (
            amount_difference <= 100
            and amount_ratio <= 0.02
        ):

            return True

        # Model has some meaningful confidence.
        if confidence >= 0.55:

            return True

        return False

    # =========================================================
    # NORMAL ML FALLBACK
    # =========================================================

    def _run_ml_fallback(
        self,
        gateway: GatewaySettlement,
        invoice: SalesInvoice | None,
        bank: BankCredit | None,
    ) -> dict[str, Any]:

        if invoice is None:

            return {
                "matched": False,
                "stage": "ml_unavailable",
                "confidence": 0.0,
                "decision": "HUMAN_REVIEW",
                "resolver": "ml",
                "reason": (
                    "No invoice candidate was available "
                    "for ML evaluation."
                ),
                "order_id": gateway.order_id,
                "settlement_id": gateway.settlement_id,
            }

        # -----------------------------------------------------
        # Build features
        # -----------------------------------------------------

        features = build_match_features(
            invoice=invoice,
            gateway=gateway,
            bank=bank,
        )

        # -----------------------------------------------------
        # ML prediction
        # -----------------------------------------------------

        prediction = self.ml_resolver.predict(
            features
        )

        decision = prediction.get(
            "decision",
            "HUMAN_REVIEW",
        )

        confidence = float(
            prediction.get(
                "confidence",
                0.0,
            )
        )

        model_prediction = prediction.get(
            "prediction"
        )

        # =====================================================
        # AUTO RESOLVE
        # =====================================================

        if (
            model_prediction == 1
            and decision == "AUTO_RESOLVE"
            and confidence
            >= self.AUTO_RESOLVE_THRESHOLD
        ):

            match = ReconciliationMatch(
                order_id=(
                    gateway.order_id
                    or invoice.order_id
                ),
                sales_invoice_id=invoice.id,
                gateway_settlement_id=gateway.id,
                status=MatchStatus.RECONCILED,
                match_stage="ml",
                variance_amount=round(
                    (
                        gateway.gross_amount
                        or 0
                    )
                    - (
                        invoice.amount
                        or 0
                    ),
                    2,
                ),
                variance_reason="ml_match",
                confidence=str(
                    confidence
                ),
            )

            self.db.add(match)
            self.db.commit()
            self.db.refresh(match)

            return {
                "matched": True,
                "stage": "ml",
                "confidence": confidence,
                "decision": "AUTO_RESOLVE",
                "resolver": "ml",
                "match_id": match.id,
                "order_id": (
                    gateway.order_id
                    or invoice.order_id
                ),
                "settlement_id": gateway.settlement_id,
                "selected_invoice": invoice.invoice_id,
                "features": features,
            }

        # =====================================================
        # AI REVIEW
        # =====================================================

        if (
            decision == "AI_REVIEW"
            or (
                model_prediction == 0
                and confidence
                >= self.AI_REVIEW_THRESHOLD
            )
        ):

            match = ReconciliationMatch(
                order_id=(
                    gateway.order_id
                    or invoice.order_id
                ),
                sales_invoice_id=invoice.id,
                gateway_settlement_id=gateway.id,
                status=MatchStatus.PENDING,
                match_stage="ml_ai_review",
                variance_amount=round(
                    (
                        gateway.gross_amount
                        or 0
                    )
                    - (
                        invoice.amount
                        or 0
                    ),
                    2,
                ),
                variance_reason="ml_uncertain",
                confidence=str(
                    confidence
                ),
            )

            self.db.add(match)
            self.db.commit()
            self.db.refresh(match)

            return {
                "matched": False,
                "stage": "ml",
                "confidence": confidence,
                "decision": "AI_REVIEW",
                "resolver": "ml",
                "match_id": match.id,
                "order_id": (
                    gateway.order_id
                    or invoice.order_id
                ),
                "settlement_id": gateway.settlement_id,
                "selected_invoice": invoice.invoice_id,
                "features": features,
                "reason": (
                    "ML found a possible match "
                    "but requires AI investigation."
                ),
            }

        # =====================================================
        # HUMAN REVIEW
        # =====================================================

        return {
            "matched": False,
            "stage": "ml",
            "confidence": confidence,
            "decision": "HUMAN_REVIEW",
            "resolver": "ml",
            "order_id": gateway.order_id,
            "settlement_id": gateway.settlement_id,
            "features": features,
            "reason": (
                "ML could not safely resolve "
                "this reconciliation."
            ),
        }

    # =========================================================
    # HUMAN REVIEW RESPONSE
    # =========================================================

    def _create_human_review_response(
        self,
        gateway: GatewaySettlement,
        candidate_results: list[dict[str, Any]],
        confidence: float,
        reason: str,
        stage: str,
    ) -> dict[str, Any]:

        return {
            "matched": False,
            "stage": stage,
            "confidence": confidence,
            "decision": "HUMAN_REVIEW",
            "resolver": "ml",
            "order_id": gateway.order_id,
            "settlement_id": gateway.settlement_id,
            "reason": reason,
            "candidates": (
                self._serialize_candidates(
                    candidate_results
                )
            ),
        }

    # =========================================================
    # SERIALIZATION
    # =========================================================

    @staticmethod
    def _serialize_candidates(
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:

        output = []

        for candidate in candidates:

            invoice = candidate["invoice"]

            prediction = candidate[
                "prediction"
            ]

            output.append(
                {
                    "invoice_id": invoice.invoice_id,
                    "order_id": invoice.order_id,
                    "amount": invoice.amount,
                    "currency": invoice.currency,
                    "candidate_score": candidate[
                        "candidate_score"
                    ],
                    "amount_difference": candidate[
                        "amount_difference"
                    ],
                    "amount_ratio": candidate[
                        "amount_ratio"
                    ],
                    "ml_prediction": prediction.get(
                        "prediction"
                    ),
                    "ml_confidence": prediction.get(
                        "confidence"
                    ),
                    "ml_decision": prediction.get(
                        "decision"
                    ),
                }
            )

        return output