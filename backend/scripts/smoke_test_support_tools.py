from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.support_tools import (  # noqa: E402
    check_refund_eligibility,
    create_case_note,
    get_customer_account,
    get_invoice,
    get_payment_attempts,
    reset_billing_fixture_cache,
)


def main() -> None:
    reset_billing_fixture_cache()
    payload = {
        "customer": get_customer_account("cust_acme").model_dump(),
        "invoice": get_invoice("inv_acme_2001_dup").model_dump(),
        "payment_attempts": [
            attempt.model_dump()
            for attempt in get_payment_attempts("cust_umbrella", "inv_umbrella_retry")
        ],
        "refund_eligibility": check_refund_eligibility("inv_acme_2001_dup", "cust_acme").model_dump(),
        "case_note": create_case_note(
            case_id="case_smoke_duplicate_charge",
            note="Reviewed duplicate charge fixture and prepared refund recommendation.",
        ).model_dump(),
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
