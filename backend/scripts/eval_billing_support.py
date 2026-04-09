from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
import sys

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.ingest import ingest_seed_docs
from app.llm import generate_structured_answer
from app.models import AnswerPayload
from app.retrieval import retrieve_chunks

DEFAULT_CASES = ROOT / "backend" / "evals" / "billing_cases.json"


@dataclass
class EvalResult:
    case_id: str
    retrieval_hit: bool
    escalation_correct: bool
    action_keyword_hit: bool
    schema_valid: bool
    top_chunk: str | None
    expected_topics: list[str]
    expected_policy_types: list[str]
    action_keywords: list[str]
    answer_confidence: str | None


def load_cases(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate_case(case: dict) -> EvalResult:
    chunks, _, _ = retrieve_chunks(case["question"], top_k=3)
    answer, _, _ = generate_structured_answer(case["question"], chunks)

    retrieved_topics = {chunk.topic for chunk in chunks if chunk.topic}
    retrieved_policy_types = {chunk.policy_type for chunk in chunks if chunk.policy_type}
    retrieval_hit = bool(
        retrieved_topics.intersection(case["expected_topics"])
        or retrieved_policy_types.intersection(case["expected_policy_types"])
    )

    action_keywords = [keyword.lower() for keyword in case["expected_action_keywords"]]
    action_text = f"{answer.answer} {answer.recommended_action}".lower()
    action_keyword_hit = any(keyword in action_text for keyword in action_keywords)
    escalation_correct = answer.escalation_required == case["expected_escalation_required"]
    schema_valid = isinstance(answer, AnswerPayload)

    return EvalResult(
        case_id=case["id"],
        retrieval_hit=retrieval_hit,
        escalation_correct=escalation_correct,
        action_keyword_hit=action_keyword_hit,
        schema_valid=schema_valid,
        top_chunk=chunks[0].chunk_id if chunks else None,
        expected_topics=case["expected_topics"],
        expected_policy_types=case["expected_policy_types"],
        action_keywords=case["expected_action_keywords"],
        answer_confidence=answer.confidence,
    )


def summarize(results: list[EvalResult]) -> dict[str, float]:
    def rate(values: list[bool]) -> float:
        return round(100 * mean(1.0 if value else 0.0 for value in values), 1) if values else 0.0

    return {
        "cases": float(len(results)),
        "retrieval_hit_rate": rate([result.retrieval_hit for result in results]),
        "schema_valid_rate": rate([result.schema_valid for result in results]),
        "escalation_accuracy": rate([result.escalation_correct for result in results]),
        "action_keyword_hit_rate": rate([result.action_keyword_hit for result in results]),
    }


def print_report(results: list[EvalResult]) -> None:
    summary = summarize(results)
    print("Billing Support Eval")
    print("====================")
    print(f"Cases: {int(summary['cases'])}")
    print(f"Retrieval hit rate: {summary['retrieval_hit_rate']}%")
    print(f"Schema valid rate: {summary['schema_valid_rate']}%")
    print(f"Escalation accuracy: {summary['escalation_accuracy']}%")
    print(f"Action keyword hit rate: {summary['action_keyword_hit_rate']}%")
    print("")

    failures = [
        result
        for result in results
        if not (
            result.retrieval_hit
            and result.schema_valid
            and result.escalation_correct
            and result.action_keyword_hit
        )
    ]
    if not failures:
        print("All cases passed the current lightweight checks.")
        return

    print("Failures")
    print("--------")
    for result in failures:
        print(
            f"{result.case_id}: retrieval_hit={result.retrieval_hit}, "
            f"schema_valid={result.schema_valid}, "
            f"escalation_correct={result.escalation_correct}, "
            f"action_keyword_hit={result.action_keyword_hit}, "
            f"top_chunk={result.top_chunk}, "
            f"expected_topics={result.expected_topics}, "
            f"expected_policy_types={result.expected_policy_types}, "
            f"action_keywords={result.action_keywords}, "
            f"confidence={result.answer_confidence}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local billing-support retrieval and answer evals.")
    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES,
        help="Path to the evaluation cases JSON file.",
    )
    parser.add_argument(
        "--skip-ingest",
        action="store_true",
        help="Skip rebuilding the local index before running evals.",
    )
    args = parser.parse_args()

    if not args.skip_ingest:
        result = ingest_seed_docs()
        print(f"Indexed {result['documents']} documents into {result['chunks']} chunks before evaluation.")
        print("")

    cases = load_cases(args.cases)
    results = [evaluate_case(case) for case in cases]
    print_report(results)


if __name__ == "__main__":
    main()
