from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

import httpx


def _load_questions(path: Path) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if not isinstance(payload.get("question"), str):
            raise ValueError(f"Line {line_number}: question must be a string")
        questions.append(payload)
    return questions


def _contains_expected_terms(answer: str, expected_terms: list[str]) -> bool:
    lowered = answer.lower()
    return all(term.lower() in lowered for term in expected_terms)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a small RAG regression evaluation set")
    parser.add_argument("--file", default="eval/questions.example.jsonl")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--document-id", default=None)
    args = parser.parse_args()

    questions = _load_questions(Path(args.file))
    if not questions:
        raise SystemExit("No questions found")

    latencies: list[float] = []
    source_hits = 0
    term_hits = 0
    citation_hits = 0

    with httpx.Client(timeout=300.0) as client:
        for item in questions:
            payload: dict[str, Any] = {"question": item["question"]}
            if args.document_id:
                payload["document_id"] = args.document_id

            started_at = time.perf_counter()
            response = client.post(
                f"{args.base_url.rstrip('/')}/api/v1/chat",
                headers={"X-API-Key": args.api_key},
                json=payload,
            )
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            latencies.append(elapsed_ms)
            response.raise_for_status()
            result = response.json()

            answer = str(result.get("answer", ""))
            sources = result.get("sources", [])
            expected_source = item.get("expected_source")
            expected_terms = item.get("expected_answer_contains", [])

            if isinstance(expected_terms, list) and _contains_expected_terms(
                answer,
                [str(term) for term in expected_terms],
            ):
                term_hits += 1
            if "[S" in answer:
                citation_hits += 1
            if expected_source and isinstance(sources, list):
                filenames = [
                    str(source.get("filename", ""))
                    for source in sources
                    if isinstance(source, dict)
                ]
                if any(str(expected_source) in filename for filename in filenames):
                    source_hits += 1

            print(
                json.dumps(
                    {
                        "question": item["question"],
                        "latency_ms": round(elapsed_ms, 2),
                        "sources": len(sources) if isinstance(sources, list) else 0,
                        "answer_preview": answer[:160],
                    },
                    ensure_ascii=False,
                )
            )

    total = len(questions)
    print("\nSummary")
    print(f"questions={total}")
    print(f"avg_latency_ms={statistics.mean(latencies):.2f}")
    print(f"p95_latency_ms={sorted(latencies)[max(0, int(total * 0.95) - 1)]:.2f}")
    print(f"source_hit_rate={source_hits / total:.2%}")
    print(f"expected_terms_hit_rate={term_hits / total:.2%}")
    print(f"citation_rate={citation_hits / total:.2%}")


if __name__ == "__main__":
    main()
