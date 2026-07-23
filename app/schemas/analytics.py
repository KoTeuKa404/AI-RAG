from __future__ import annotations

from pydantic import BaseModel


class FeedbackMetrics(BaseModel):
    responses: int
    average_rating: float | None
    coverage: float


class AnalyticsSummary(BaseModel):
    period_days: int
    documents_by_status: dict[str, int]
    chat_requests: int
    unique_actors: int
    feedback: FeedbackMetrics
