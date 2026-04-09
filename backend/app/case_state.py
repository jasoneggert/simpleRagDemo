from __future__ import annotations

import json
from datetime import UTC, datetime

from app.models import ActionProposal, AnswerPayload, CaseStateSnapshot, CaseStateSummary, CaseTurn, ToolTraceEntry
from app.support_db import describe_db_location, get_db_connection


def load_case_state(case_id: str) -> CaseStateSnapshot | None:
    with get_db_connection() as connection:
        case_row = connection.execute(
            """
            SELECT case_id, workspace_id, customer_id, invoice_id, last_question, last_updated_at
            FROM cases
            WHERE case_id = ?
            """,
            (case_id,),
        ).fetchone()
        if case_row is None:
            return None

        turn_rows = connection.execute(
            """
            SELECT turn_id, asked_at, question, answer, recommended_action, escalation_required, tool_trace_json, action_proposal_json
            FROM case_turns
            WHERE case_id = ?
            ORDER BY asked_at ASC
            """,
            (case_id,),
        ).fetchall()

    turns = [
        CaseTurn(
            turn_id=row["turn_id"],
            asked_at=row["asked_at"],
            question=row["question"],
            answer=row["answer"],
            recommended_action=row["recommended_action"],
            escalation_required=bool(row["escalation_required"]),
            tool_trace=[ToolTraceEntry.model_validate(item) for item in json.loads(row["tool_trace_json"])],
            action_proposal=(
                None
                if row["action_proposal_json"] is None
                else ActionProposal.model_validate(json.loads(row["action_proposal_json"]))
            ),
        )
        for row in turn_rows
    ]

    open_action_type = turns[-1].action_proposal.action_type if turns and turns[-1].action_proposal is not None else None
    return CaseStateSnapshot(
        case_id=case_row["case_id"],
        workspace_id=case_row["workspace_id"],
        customer_id=case_row["customer_id"],
        invoice_id=case_row["invoice_id"],
        turn_count=len(turns),
        last_question=case_row["last_question"],
        last_updated_at=case_row["last_updated_at"],
        open_action_type=open_action_type,
        notes_path=describe_db_location("case_notes", case_id),
        turns=turns,
    )


def summarize_case_state(state: CaseStateSnapshot) -> CaseStateSummary:
    open_action_type = None
    if state.turns and state.turns[-1].action_proposal is not None:
        open_action_type = state.turns[-1].action_proposal.action_type

    return CaseStateSummary(
        case_id=state.case_id,
        workspace_id=state.workspace_id,
        customer_id=state.customer_id,
        invoice_id=state.invoice_id,
        turn_count=len(state.turns),
        last_question=state.turns[-1].question if state.turns else None,
        last_updated_at=state.last_updated_at,
        open_action_type=open_action_type,
    )


def build_case_context(state: CaseStateSnapshot | None) -> str | None:
    if state is None:
        return None

    lines: list[str] = []
    if state.workspace_id:
        lines.append(f"Remembered workspace_id: {state.workspace_id}")
    if state.customer_id:
        lines.append(f"Remembered customer_id: {state.customer_id}")
    if state.invoice_id:
        lines.append(f"Remembered invoice_id: {state.invoice_id}")

    recent_turns = state.turns[-3:]
    if recent_turns:
        lines.append("Recent case history:")
        for turn in recent_turns:
            lines.append(f"- Prior question: {turn.question}")
            lines.append(f"- Prior answer: {turn.answer}")
            lines.append(f"- Prior recommended action: {turn.recommended_action}")
            if turn.action_proposal is not None:
                lines.append(f"- Pending or prior proposed action: {turn.action_proposal.action_type}")

    return "\n".join(lines) if lines else None


def save_case_turn(
    *,
    case_id: str,
    workspace_id: str | None,
    customer_id: str | None,
    invoice_id: str | None,
    question: str,
    answer: AnswerPayload,
    tool_trace: list[ToolTraceEntry],
    action_proposal: ActionProposal | None,
) -> CaseStateSnapshot:
    now = datetime.now(UTC).isoformat()
    existing = load_case_state(case_id)
    next_turn_number = 1 if existing is None else len(existing.turns) + 1
    turn_id = f"{case_id}-turn-{next_turn_number}"

    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO cases(case_id, workspace_id, customer_id, invoice_id, last_question, last_updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(case_id) DO UPDATE SET
                workspace_id = excluded.workspace_id,
                customer_id = excluded.customer_id,
                invoice_id = excluded.invoice_id,
                last_question = excluded.last_question,
                last_updated_at = excluded.last_updated_at
            """,
            (
                case_id,
                workspace_id or (existing.workspace_id if existing is not None else None),
                customer_id or (existing.customer_id if existing is not None else None),
                invoice_id or (existing.invoice_id if existing is not None else None),
                question,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO case_turns(
                turn_id,
                case_id,
                asked_at,
                question,
                answer,
                recommended_action,
                escalation_required,
                tool_trace_json,
                action_proposal_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                turn_id,
                case_id,
                now,
                question,
                answer.answer,
                answer.recommended_action,
                1 if answer.escalation_required else 0,
                json.dumps([entry.model_dump() for entry in tool_trace]),
                None if action_proposal is None else json.dumps(action_proposal.model_dump()),
            ),
        )

    snapshot = load_case_state(case_id)
    if snapshot is None:
        raise RuntimeError(f"Failed to persist case state for {case_id}.")
    return snapshot


def append_case_note(case_id: str, note: str, author: str, created_at: str) -> str:
    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO case_notes(case_id, note, author, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (case_id, note, author, created_at),
        )
    return describe_db_location("case_notes", case_id)


def reset_case_state(case_id: str) -> None:
    with get_db_connection() as connection:
        connection.execute("DELETE FROM case_notes WHERE case_id = ?", (case_id,))
        connection.execute("DELETE FROM case_turns WHERE case_id = ?", (case_id,))
        connection.execute("DELETE FROM cases WHERE case_id = ?", (case_id,))
