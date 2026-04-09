from __future__ import annotations

import json
from datetime import UTC, datetime

from app.models import ActionExecutionSummary, IncidentSummary, ObservabilityEvent
from app.support_db import describe_db_location, get_db_connection


def append_observability_event(event: dict[str, object]) -> str:
    payload = {
        "recorded_at": datetime.now(UTC).isoformat(),
        **event,
    }
    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO observability_events(recorded_at, payload_json)
            VALUES (?, ?)
            """,
            (payload["recorded_at"], json.dumps(payload, sort_keys=True)),
        )
    return describe_db_location("observability_events")


def list_observability_events(limit: int = 20) -> list[ObservabilityEvent]:
    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT payload_json
            FROM observability_events
            ORDER BY recorded_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [ObservabilityEvent.model_validate(json.loads(row["payload_json"])) for row in rows]


def list_recent_actions(limit: int = 10) -> list[ActionExecutionSummary]:
    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT action_type, status, result_summary, payload_json, created_at
            FROM action_executions
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    actions: list[ActionExecutionSummary] = []
    for row in rows:
        payload = json.loads(row["payload_json"])
        actions.append(
            ActionExecutionSummary(
                action_type=row["action_type"],
                status=row["status"],
                result_summary=row["result_summary"],
                workspace_id=payload.get("workspace_id"),
                customer_id=payload.get("customer_id"),
                invoice_id=payload.get("invoice_id"),
                created_at=row["created_at"],
            )
        )
    return actions


def build_incident_summary() -> IncidentSummary:
    events = list_observability_events(limit=100)
    guardrail_block_count = sum(1 for event in events if event.status == "guardrail_blocked")
    unauthorized_count = sum(1 for event in events if event.guardrail_reason == "unauthorized")
    high_latency_count = sum(
        1 for event in events if (event.latency_ms or 0) > 5000 or event.guardrail_reason == "latency_budget_exceeded"
    )
    token_budget_block_count = sum(1 for event in events if event.guardrail_reason == "token_budget_exceeded")
    unsupported_case_count = sum(1 for event in events if event.guardrail_reason == "unsupported_case")
    recent_failures = [
        event
        for event in events
        if event.status != "ok" or (event.tool_error_count or 0) > 0
    ][:10]
    return IncidentSummary(
        total_events=len(events),
        guardrail_block_count=guardrail_block_count,
        unauthorized_count=unauthorized_count,
        high_latency_count=high_latency_count,
        token_budget_block_count=token_budget_block_count,
        unsupported_case_count=unsupported_case_count,
        recent_failures=recent_failures,
        recent_actions=list_recent_actions(limit=10),
    )
