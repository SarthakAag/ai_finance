from pydantic import BaseModel
from datetime import datetime


class ReconciliationSummary(BaseModel):
    exact: int
    fuzzy_mdr: int
    split_payment: int
    exceptions: int
    total: int

    @property
    def resolved_without_llm_pct(self) -> float:
        if self.total == 0:
            return 0.0
        resolved = self.exact + self.fuzzy_mdr + self.split_payment
        return round(100 * resolved / self.total, 1)


class MatchOut(BaseModel):
    id: str
    order_id: str
    status: str
    match_stage: str | None
    variance_amount: float | None
    variance_reason: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class TraceOut(BaseModel):
    id: str
    step_number: int
    tool_name: str
    tool_input: dict
    tool_output: dict
    reasoning: str | None
    tokens_used: int | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class TicketOut(BaseModel):
    id: str
    subject: str
    body: str
    expected_amount: float | None
    actual_amount: float | None
    missing_fields: list
    resolved: bool = False
    resolution_note: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True