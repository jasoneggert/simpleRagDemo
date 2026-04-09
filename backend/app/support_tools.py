from __future__ import annotations

import json
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field

from app.case_state import append_case_note
from app.config import settings
from app.support_db import describe_db_location, get_db_connection


class CustomerAccount(BaseModel):
    customer_id: str
    workspace_id: str
    name: str
    billing_email: str
    plan: str
    status: Literal["active", "grace-period", "read-only", "cancelled"]
    region: str
    tax_id_on_file: bool
    renewal_date: str
    payment_method_status: str
    api_calls_since_renewal: int
    data_exports_since_renewal: int
    invited_users_since_renewal: int


class InvoiceRecord(BaseModel):
    invoice_id: str
    customer_id: str
    workspace_id: str
    amount_cents: int
    currency: str
    status: Literal["paid", "open", "void"]
    issued_at: str
    paid_at: str | None = None
    tax_cents: int
    billing_reason: str
    duplicate_group: str | None = None


class PaymentAttempt(BaseModel):
    attempt_id: str
    invoice_id: str
    customer_id: str
    status: Literal["succeeded", "failed"]
    processor_reference: str | None = None
    decline_code: str | None = None
    attempted_at: str
    card_last4: str


class RefundEligibilityResult(BaseModel):
    eligible: bool
    reason: str
    qualifying_policy: str
    recommended_action: str
    requires_manual_review: bool


class CaseNoteRecord(BaseModel):
    case_id: str
    note: str = Field(min_length=8)
    author: str
    created_at: str
    persisted_to: str


class BillingFixtureStore(BaseModel):
    customers: list[CustomerAccount]
    invoices: list[InvoiceRecord]
    payment_attempts: list[PaymentAttempt]


class ActionExecutionRecord(BaseModel):
    action_type: Literal["issue_refund_request", "escalate_to_finance", "send_receipt_email"]
    status: Literal["executed"]
    result_summary: str
    payload: dict[str, str | int | bool | None]
    persisted_to: str


@lru_cache(maxsize=1)
def load_billing_fixture_store() -> BillingFixtureStore:
    payload = json.loads(settings.support_fixtures_path.read_text(encoding="utf-8"))
    return BillingFixtureStore.model_validate(payload)


def reset_billing_fixture_cache() -> None:
    load_billing_fixture_store.cache_clear()


def _validate_workspace_scope(
    *,
    expected_workspace_id: str | None,
    customer: CustomerAccount | None = None,
    invoice: InvoiceRecord | None = None,
) -> str | None:
    resolved = expected_workspace_id
    if customer is not None:
        if resolved is None:
            resolved = customer.workspace_id
        elif customer.workspace_id != resolved:
            raise ValueError("Customer does not belong to the supplied workspace.")
    if invoice is not None:
        if resolved is None:
            resolved = invoice.workspace_id
        elif invoice.workspace_id != resolved:
            raise ValueError("Invoice does not belong to the supplied workspace.")
    if customer is not None and invoice is not None and customer.workspace_id != invoice.workspace_id:
        raise ValueError("Customer and invoice do not belong to the same workspace.")
    return resolved


def resolve_workspace_scope(
    *,
    workspace_id: str | None = None,
    customer_id: str | None = None,
    invoice_id: str | None = None,
) -> str | None:
    customer = get_customer_account(customer_id, workspace_id=workspace_id) if customer_id else None
    invoice = get_invoice(invoice_id, workspace_id=workspace_id) if invoice_id else None
    return _validate_workspace_scope(
        expected_workspace_id=workspace_id,
        customer=customer,
        invoice=invoice,
    )


def get_customer_account(customer_id: str, workspace_id: str | None = None) -> CustomerAccount:
    store = load_billing_fixture_store()
    for customer in store.customers:
        if customer.customer_id == customer_id:
            _validate_workspace_scope(expected_workspace_id=workspace_id, customer=customer)
            return customer
    raise ValueError(f"Unknown customer_id: {customer_id}")


def get_invoice(invoice_id: str, workspace_id: str | None = None) -> InvoiceRecord:
    store = load_billing_fixture_store()
    for invoice in store.invoices:
        if invoice.invoice_id == invoice_id:
            _validate_workspace_scope(expected_workspace_id=workspace_id, invoice=invoice)
            return invoice
    raise ValueError(f"Unknown invoice_id: {invoice_id}")


def get_payment_attempts(
    customer_id: str,
    invoice_id: str | None = None,
    workspace_id: str | None = None,
) -> list[PaymentAttempt]:
    customer = get_customer_account(customer_id, workspace_id=workspace_id)
    resolved_workspace_id = customer.workspace_id
    store = load_billing_fixture_store()
    attempts = [attempt for attempt in store.payment_attempts if attempt.customer_id == customer_id]
    if invoice_id is not None:
        invoice = get_invoice(invoice_id, workspace_id=resolved_workspace_id)
        if invoice.customer_id != customer.customer_id:
            raise ValueError("Invoice does not belong to the supplied customer.")
        attempts = [attempt for attempt in attempts if attempt.invoice_id == invoice_id]
    return sorted(attempts, key=lambda attempt: attempt.attempted_at)


def check_refund_eligibility(
    invoice_id: str,
    customer_id: str,
    workspace_id: str | None = None,
) -> RefundEligibilityResult:
    invoice = get_invoice(invoice_id, workspace_id=workspace_id)
    customer = get_customer_account(customer_id, workspace_id=workspace_id)
    _validate_workspace_scope(expected_workspace_id=workspace_id, customer=customer, invoice=invoice)

    if invoice.customer_id != customer.customer_id:
        raise ValueError("Invoice does not belong to the supplied customer.")

    if invoice.duplicate_group:
        related_paid = [
            candidate
            for candidate in load_billing_fixture_store().invoices
            if candidate.duplicate_group == invoice.duplicate_group and candidate.status == "paid"
        ]
        if len(related_paid) >= 2:
            return RefundEligibilityResult(
                eligible=True,
                reason="Two paid invoices share the same duplicate group and amount pattern.",
                qualifying_policy="duplicate_charge_policy",
                recommended_action="Review the duplicate charges and refund the later duplicate payment if there was no intentional second workspace purchase.",
                requires_manual_review=False,
            )

    if customer.plan.endswith("monthly") and customer.api_calls_since_renewal < 25:
        return RefundEligibilityResult(
            eligible=True,
            reason="Monthly plan is within the documented low-usage refund window.",
            qualifying_policy="refund_policy",
            recommended_action="Confirm the renewal date and issue a refund if the charge is still within 14 calendar days.",
            requires_manual_review=False,
        )

    if customer.plan.endswith("annual") and customer.data_exports_since_renewal == 0 and customer.invited_users_since_renewal <= 3:
        return RefundEligibilityResult(
            eligible=True,
            reason="Annual plan is within the documented low-activity refund window.",
            qualifying_policy="refund_policy",
            recommended_action="Verify the renewal occurred within 30 calendar days and approve the refund if no disqualifying usage occurred.",
            requires_manual_review=False,
        )

    if invoice.tax_cents > 0:
        return RefundEligibilityResult(
            eligible=False,
            reason="The invoice includes tax and tax refunds require finance review after finalization.",
            qualifying_policy="tax_policy",
            recommended_action="Do not manually refund the tax portion; escalate to finance if the customer disputes tax handling.",
            requires_manual_review=True,
        )

    return RefundEligibilityResult(
        eligible=False,
        reason="The invoice does not meet the fixture rules for automatic refund eligibility.",
        qualifying_policy="refund_policy",
        recommended_action="Explain the applicable policy and escalate only if the customer requests an exception above policy.",
        requires_manual_review=False,
    )


def create_case_note(case_id: str, note: str, author: str = "support-bot") -> CaseNoteRecord:
    created_at = "local-fixture"
    persisted_to = append_case_note(case_id=case_id, note=note, author=author, created_at=created_at)
    record = CaseNoteRecord(
        case_id=case_id,
        note=note,
        author=author,
        created_at=created_at,
        persisted_to=persisted_to,
    )
    return record


def _append_action_record(record: ActionExecutionRecord) -> ActionExecutionRecord:
    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO action_executions(action_type, status, result_summary, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                record.action_type,
                record.status,
                record.result_summary,
                json.dumps(record.payload, sort_keys=True),
                "local-fixture",
            ),
        )
    return record.model_copy(update={"persisted_to": describe_db_location("action_executions")})


def issue_refund_request(
    customer_id: str,
    invoice_id: str,
    reason: str,
    workspace_id: str | None = None,
) -> ActionExecutionRecord:
    customer = get_customer_account(customer_id, workspace_id=workspace_id)
    invoice = get_invoice(invoice_id, workspace_id=workspace_id)
    resolved_workspace_id = _validate_workspace_scope(
        expected_workspace_id=workspace_id,
        customer=customer,
        invoice=invoice,
    )
    if invoice.customer_id != customer.customer_id:
        raise ValueError("Invoice does not belong to the supplied customer.")
    return _append_action_record(
        ActionExecutionRecord(
            action_type="issue_refund_request",
            status="executed",
            result_summary=(
                f"Mock refund request recorded for {invoice_id} ({invoice.amount_cents} {invoice.currency}) "
                f"for customer {customer_id}."
            ),
            payload={
                "workspace_id": resolved_workspace_id,
                "customer_id": customer_id,
                "invoice_id": invoice_id,
                "reason": reason,
            },
            persisted_to=describe_db_location("action_executions"),
        )
    )


def escalate_to_finance(
    customer_id: str | None,
    invoice_id: str | None,
    reason: str,
    workspace_id: str | None = None,
) -> ActionExecutionRecord:
    customer = get_customer_account(customer_id, workspace_id=workspace_id) if customer_id else None
    invoice = get_invoice(invoice_id, workspace_id=workspace_id) if invoice_id else None
    resolved_workspace_id = _validate_workspace_scope(
        expected_workspace_id=workspace_id,
        customer=customer,
        invoice=invoice,
    )
    return _append_action_record(
        ActionExecutionRecord(
            action_type="escalate_to_finance",
            status="executed",
            result_summary=(
                f"Mock finance escalation recorded for customer {customer_id or 'unknown'} "
                f"and invoice {invoice_id or 'none'}."
            ),
            payload={
                "workspace_id": resolved_workspace_id,
                "customer_id": customer_id,
                "invoice_id": invoice_id,
                "reason": reason,
            },
            persisted_to=describe_db_location("action_executions"),
        )
    )


def send_receipt_email(
    customer_id: str,
    invoice_id: str,
    workspace_id: str | None = None,
) -> ActionExecutionRecord:
    customer = get_customer_account(customer_id, workspace_id=workspace_id)
    invoice = get_invoice(invoice_id, workspace_id=workspace_id)
    resolved_workspace_id = _validate_workspace_scope(
        expected_workspace_id=workspace_id,
        customer=customer,
        invoice=invoice,
    )
    if invoice.customer_id != customer.customer_id:
        raise ValueError("Invoice does not belong to the supplied customer.")
    return _append_action_record(
        ActionExecutionRecord(
            action_type="send_receipt_email",
            status="executed",
            result_summary=(
                f"Mock receipt email send recorded for invoice {invoice_id} to {customer.billing_email}."
            ),
            payload={"workspace_id": resolved_workspace_id, "customer_id": customer_id, "invoice_id": invoice_id},
            persisted_to=describe_db_location("action_executions"),
        )
    )
