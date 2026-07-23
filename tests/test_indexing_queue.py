from __future__ import annotations

import uuid

from app.services.indexing_queue import IndexingJob, raw_document_key


def test_indexing_job_round_trip() -> None:
    document_id = uuid.uuid4()
    job = IndexingJob(document_id=document_id, workspace_id="demo", media_type="text/plain")

    restored = IndexingJob.from_json(job.to_json())

    assert restored == job


def test_raw_document_key_contains_document_id() -> None:
    document_id = uuid.uuid4()

    assert str(document_id) in raw_document_key(document_id)
