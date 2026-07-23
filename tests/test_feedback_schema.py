import pytest
from pydantic import ValidationError

from app.schemas.chat import ChatFeedbackRequest


def test_feedback_accepts_rating_and_comment() -> None:
    feedback = ChatFeedbackRequest(rating=5, comment="Useful answer")

    assert feedback.rating == 5


def test_feedback_rejects_out_of_range_rating() -> None:
    with pytest.raises(ValidationError):
        ChatFeedbackRequest(rating=6)
