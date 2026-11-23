# ADR-007: Unified pricing, dealership credit and central payment collection

- **Status:** Accepted
- **Date:** 2026-11-23

## Context
AutoTramita.es needs unified retail prices, dealership-funded customer discounts, central card payments and tightly controlled B2B credit exposure.

## Decision
- AutoTramita controls one public retail service price list. Dealerships may grant their customers a discount, funded entirely by the dealership; AutoTramita's agreed service amount is not reduced.
- Statutory fees and taxes are accounted for separately from platform service prices.
- Only AutoTramita administrators set dealership credit limits, payment terms, billing cycles, grace periods and credit status.
- New dealerships can be prepaid-only; approved dealerships may extend deferred payment to their own customers within AutoTramita's credit facility. The dealership owes AutoTramita irrespective of customer collection.
- Payment terms may be individualized per dealership (e.g. immediate, 15, 30 or 60 days).
- Track reserved credit, utilized credit, unpaid receivables and available credit without double-counting; financial events are auditable and idempotent.
- Centralized card collection through an integrated payment service provider; SEPA Direct Debit may be used for authorized dealership collections, with mandate and notification requirements.
- If an obligation remains unpaid after **three applicable business days beyond due date**, suspend **new credit usage only**. The dealership can continue using the platform with prepaid payments; existing cases are not automatically canceled.
- Do not mark pending SEPA/card collection as settled until payment confirmation. Reactivate credit after confirmed settlement of all overdue obligations, subject to other restrictions; refunds/chargebacks trigger reassessment.
- Never silently modify existing invoice maturities when changing a dealership's terms.

## Consequences
Requires separate receivable, collection-attempt, credit-reservation, payment-ledger and audit concepts, plus webhook deduplication and reconciliation.

## Open decisions
Payment provider selection; merchant-of-record and funds flow (including whether regulated marketplace payment services are involved); definition of applicable business-day holiday calendar; treatment of in-flight SEPA during grace period; detailed dunning/escalation policy; exact discount and invoice allocation mechanics. These must be settled before implementing payment flows.

## Scope
Architecture and business rules only; not legal or payments-compliance approval.
