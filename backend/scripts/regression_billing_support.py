from __future__ import annotations

import sys
from pathlib import Path

import asyncio

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.case_state import load_case_state, reset_case_state
from app.ingest import ingest_seed_docs
from app.main import approve_action, ask_docs, get_ops_events, get_ops_summary
from app.models import ApproveActionRequest, AskRequest
from app.support_tools import issue_refund_request


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_regression_suite() -> None:
    def call_ask(request: AskRequest, authorization: str | None = None):
        return asyncio.run(ask_docs(request, authorization=authorization))

    ingest_seed_docs()
    admin_auth = "Bearer demo-admin-token"
    support_auth = "Bearer demo-support-token"

    duplicate = call_ask(
        AskRequest(
            question="A customer says they were charged twice for the same invoice within a day. What should support do?",
            top_k=3,
            customer_id="cust_acme",
            invoice_id="inv_acme_2001_dup",
        ),
        authorization=admin_auth,
    )
    assert_true(not duplicate.answer.escalation_required, "Duplicate-charge case should not escalate.")
    assert_true(
        duplicate.debug.action_proposal is not None
        and duplicate.debug.action_proposal.action_type == "issue_refund_request",
        "Duplicate-charge case should propose a refund workflow.",
    )
    assert_true(duplicate.debug.execution.cache_hit_count == 0, "Demo agent should report zero cache hits.")
    assert_true(duplicate.debug.execution.tool_calls_made >= 1, "Execution metrics should report tool usage.")

    vat = call_ask(
        AskRequest(
            question="Can support manually refund VAT after an invoice has been finalized?",
            top_k=3,
            workspace_id="ws_globex",
            customer_id="cust_globex",
            invoice_id="inv_globex_annual",
        ),
        authorization=admin_auth,
    )
    assert_true(vat.answer.escalation_required, "Finalized VAT refund case should escalate.")

    receipt = call_ask(
        AskRequest(
            question="If the customer cannot access the billing portal, what should support do for the receipt?",
            top_k=3,
            customer_id="cust_acme",
            invoice_id="inv_acme_2001_dup",
        ),
        authorization=admin_auth,
    )
    assert_true(
        receipt.debug.action_proposal is not None
        and receipt.debug.action_proposal.action_type == "send_receipt_email",
        "Receipt case should propose a resend action.",
    )

    chargeback = call_ask(
        AskRequest(
            question="The customer filed a chargeback. What should support do?",
            top_k=3,
        ),
        authorization=admin_auth,
    )
    assert_true(chargeback.answer.escalation_required, "Chargeback case should escalate.")

    case_id = "regression_case_memory"
    reset_case_state(case_id)
    first_turn = call_ask(
        AskRequest(
            question="A customer says they were charged twice for the same invoice within a day. What should support do?",
            top_k=3,
            case_id=case_id,
            customer_id="cust_acme",
            invoice_id="inv_acme_2001_dup",
        ),
        authorization=admin_auth,
    )
    second_turn = call_ask(
        AskRequest(
            question="Should we just send the receipt as well?",
            top_k=3,
            case_id=case_id,
        ),
        authorization=admin_auth,
    )
    state = load_case_state(case_id)
    assert_true(first_turn.debug.case_state_summary is not None, "First turn should return case state summary.")
    assert_true(second_turn.debug.case_state_summary is not None, "Second turn should return case state summary.")
    assert_true(state is not None and len(state.turns) == 2, "Case state should persist two turns.")
    assert_true(state is not None and state.customer_id == "cust_acme", "Case state should remember customer_id.")
    assert_true(
        state is not None and state.invoice_id == "inv_acme_2001_dup",
        "Case state should remember invoice_id.",
    )
    assert_true(state is not None and "#case_notes:" in state.notes_path, "Case notes should be persisted in the database.")
    reset_case_state(case_id)

    action = issue_refund_request(
        workspace_id="ws_acme",
        customer_id="cust_acme",
        invoice_id="inv_acme_2001_dup",
        reason="Regression test refund execution.",
    )
    assert_true("#action_executions" in action.persisted_to, "Action execution should be persisted in the database.")

    support_duplicate = call_ask(
        AskRequest(
            question="A customer says they were charged twice for the same invoice within a day. What should support do?",
            top_k=3,
            workspace_id="ws_acme",
            customer_id="cust_acme",
            invoice_id="inv_acme_2001_dup",
        ),
        authorization=support_auth,
    )
    assert_true(support_duplicate.debug.workspace_id == "ws_acme", "Support operator should access allowed workspace.")

    try:
        call_ask(
            AskRequest(
                question="Can support manually refund VAT after an invoice has been finalized?",
                top_k=3,
                workspace_id="ws_globex",
                customer_id="cust_globex",
                invoice_id="inv_globex_annual",
            ),
            authorization=support_auth,
        )
    except HTTPException as exc:
        assert_true(exc.status_code == 403, "Support operator should be blocked from unauthorized workspace.")
    else:
        raise AssertionError("Support operator unexpectedly accessed an unauthorized workspace.")

    try:
        get_ops_summary(authorization=support_auth)
    except HTTPException as exc:
        assert_true(exc.status_code == 403, "Support operator should not access admin incident views.")
    else:
        raise AssertionError("Support operator unexpectedly accessed ops summary.")

    try:
        approve_action(
            ApproveActionRequest(
                action_type="issue_refund_request",
                payload={
                    "workspace_id": "ws_acme",
                    "customer_id": "cust_acme",
                    "invoice_id": "inv_acme_2001_dup",
                    "reason": "Refund approval regression check.",
                },
            ),
            authorization=support_auth,
        )
    except HTTPException as exc:
        assert_true(exc.status_code == 403, "Support operator should not approve refund executions.")
    else:
        raise AssertionError("Support operator unexpectedly approved a refund.")

    approved = approve_action(
        ApproveActionRequest(
            action_type="issue_refund_request",
            payload={
                "workspace_id": "ws_acme",
                "customer_id": "cust_acme",
                "invoice_id": "inv_acme_2001_dup",
                "reason": "Admin approval regression check.",
            },
        ),
        authorization=admin_auth,
    )
    assert_true(approved.status == "executed", "Support admin should be able to approve refunds.")

    summary = get_ops_summary(authorization=admin_auth)
    events = get_ops_events(authorization=admin_auth, limit=20)
    assert_true(summary.total_events >= 1, "Ops summary should report recorded observability events.")
    assert_true(summary.unauthorized_count >= 1, "Ops summary should count unauthorized access attempts.")
    assert_true(any(event.guardrail_reason == "unauthorized" for event in events), "Ops events should include unauthorized audit events.")

    print("Billing support regression suite passed.")


if __name__ == "__main__":
    run_regression_suite()
