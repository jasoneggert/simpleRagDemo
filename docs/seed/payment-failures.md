# Payment Failure Playbook

## Soft declines

A soft decline usually means the issuing bank temporarily rejected the charge. Tell the customer to
retry the payment method, confirm the card has online recurring payments enabled, and contact their
bank if the next retry also fails.

## Hard declines

Hard declines include expired cards, closed accounts, and invalid card numbers. Support should ask
the customer to replace the card on file. Do not promise that retrying the same card will work.

## Retry schedule

The billing system retries failed renewals after 1 day, 3 days, and 5 days. During the retry
window, the workspace remains active. If all retries fail, the workspace is moved to read-only
mode on day 7.

## Escalation triggers

Escalate to finance operations when a customer reports a failed charge but the dashboard shows the
invoice as paid, when the payment processor reference is missing, or when multiple workspaces fail
on the same card within 1 hour.
