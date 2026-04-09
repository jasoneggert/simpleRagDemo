from __future__ import annotations

import json
import secrets
from functools import lru_cache

from fastapi import HTTPException
from pydantic import BaseModel

from app.config import settings
from app.models import ActionType, OperatorRole, OperatorSession


class OperatorRecord(BaseModel):
    operator_id: str
    name: str
    role: OperatorRole
    token: str
    allowed_workspaces: list[str]
    can_ingest: bool = False


class OperatorStore(BaseModel):
    operators: list[OperatorRecord]


@lru_cache(maxsize=1)
def load_operator_store() -> OperatorStore:
    payload = json.loads(settings.support_operators_path.read_text(encoding="utf-8"))
    return OperatorStore.model_validate(payload)


def reset_operator_store_cache() -> None:
    load_operator_store.cache_clear()


def authenticate_operator(authorization: str | None) -> OperatorRecord:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Authorization header must be a Bearer token.")

    for operator in load_operator_store().operators:
        if secrets.compare_digest(operator.token, token):
            return operator
    raise HTTPException(status_code=401, detail="Invalid operator token.")


def to_session(operator: OperatorRecord) -> OperatorSession:
    return OperatorSession(
        operator_id=operator.operator_id,
        name=operator.name,
        role=operator.role,
        allowed_workspaces=operator.allowed_workspaces,
        can_ingest=operator.can_ingest,
    )


def require_workspace_access(operator: OperatorRecord, workspace_id: str | None) -> None:
    if workspace_id is None:
        return
    if workspace_id not in operator.allowed_workspaces:
        raise HTTPException(
            status_code=403,
            detail=f"Operator {operator.operator_id} is not allowed to access workspace {workspace_id}.",
        )


def require_ingest_permission(operator: OperatorRecord) -> None:
    if not operator.can_ingest:
        raise HTTPException(status_code=403, detail="Operator is not allowed to rebuild the policy index.")


def require_case_reset_permission(operator: OperatorRecord) -> None:
    if operator.role not in ("support_admin", "finance_admin"):
        raise HTTPException(status_code=403, detail="Operator is not allowed to reset persisted case state.")


def require_action_approval_permission(operator: OperatorRecord, action_type: ActionType) -> None:
    if action_type == "send_receipt_email":
        return
    if action_type == "escalate_to_finance":
        return
    if action_type == "issue_refund_request" and operator.role not in ("support_admin", "finance_admin"):
        raise HTTPException(status_code=403, detail="Operator is not allowed to approve refund requests.")


def require_ops_access(operator: OperatorRecord) -> None:
    if operator.role not in ("support_admin", "finance_admin"):
        raise HTTPException(status_code=403, detail="Operator is not allowed to access operational incident views.")
