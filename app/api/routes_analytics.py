from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import DbSession, PrincipalContext
from app.core.auth import require_roles
from app.db.models import ChatLog, Document
from app.schemas.analytics import AnalyticsSummary, FeedbackMetrics

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@router.get("/summary", response_model=AnalyticsSummary)
async def analytics_summary(
    session: DbSession,
    principal: PrincipalContext,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> AnalyticsSummary:
    require_roles(principal, "owner", "admin")
    since = datetime.now(UTC) - timedelta(days=days)

    document_rows = (
        await session.execute(
            select(Document.status, func.count(Document.id))
            .where(Document.workspace_id == principal.workspace_id)
            .group_by(Document.status)
        )
    ).all()
    documents_by_status = {str(row.status): int(row[1]) for row in document_rows}

    chat_stats = (
        await session.execute(
            select(
                func.count(ChatLog.id),
                func.count(func.distinct(ChatLog.actor_id)),
                func.count(ChatLog.feedback_rating),
                func.avg(ChatLog.feedback_rating),
            ).where(
                ChatLog.workspace_id == principal.workspace_id,
                ChatLog.created_at >= since,
            )
        )
    ).one()

    chat_requests = int(chat_stats[0] or 0)
    unique_actors = int(chat_stats[1] or 0)
    feedback_responses = int(chat_stats[2] or 0)
    average_rating = round(float(chat_stats[3]), 2) if chat_stats[3] is not None else None
    coverage = round(feedback_responses / chat_requests, 4) if chat_requests else 0.0

    return AnalyticsSummary(
        period_days=days,
        documents_by_status=documents_by_status,
        chat_requests=chat_requests,
        unique_actors=unique_actors,
        feedback=FeedbackMetrics(
            responses=feedback_responses,
            average_rating=average_rating,
            coverage=coverage,
        ),
    )
