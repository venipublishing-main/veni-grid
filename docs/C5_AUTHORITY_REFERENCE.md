# Veni Grid C5 — Version, approval, publication pointer and rollback reference (v0.1)

**Status: executed transactional research prototype, not production authentication or publication.** No login service, remote API, hosted database, organisation membership provider, live school record or operational timetable is connected. All test accounts and learning data are synthetic.

## Identity and authority boundary

Grid belongs in Veni Flow and should consume **verified Veni Account identity** from the existing shared account layer. That does **not** grant the account-holder authority over school, sport, examinations or invigilation data. Each organisation and scheduling namespace independently grants permissions. Never merge records across products or independently run databases because emails happen to match. The future Veni Flow database is a separate organisation/security boundary. A production session verifier, tenant membership authority, row-level security policy and backend API are **not** implemented in C5.

`Principal(organisation_id, subject_id)` is an **in-process, trusted-adapter input** only; it is *not* an authentication credential or claim-verification function. A web request must never instantiate it from unvalidated browser JSON, an unverified JWT, a guessed email or a parameter such as `is_admin=true`. The SQLite reference has **no network endpoint**. `development_bootstrap=True` is required to create synthetic organisations and owner memberships. Bootstrap is disabled by default and must never be exposed in production routes.

## Precisely what C5 implements today

- Tenant-scoped schedule namespaces, memberships, and **exact per-schedule grants** for `view`, `propose`, `approve`, `publish` and `restore`. Unrecognised or ungranted permissions fail closed. The reference owner can delegate with a reason; membership is independent of universal Veni login.
- **Staging:** a `C4Result` is accepted only with `PROPOSED_VALIDATED`, real C2 independent hard validation, complete O1 request validation, a valid `review_errors` result, source tenant/schedule identity and matching current accepted version/hash. A staged proposal does not change the current version or publish anything.
- **Approval:** a different authorised actor (two-person maker/checker) submits an explicit reason and expected revision. The store recomputes the C4 independent review using the **stored** immutable proposal, then atomically performs a compare-and-swap against the current head. It writes a new immutable **O1 option-plan** version; it does **not** approve/publish the separate C2 teaching timetable.
- **Publication:** an independently granted publisher must perform a separate, reasoned operation. Here it advances a **local option-version pointer only**, not an external website, email, timetabling app or school notice.
- **Restore:** an independently authorised actor copies a previously accepted immutable version into a **new head revision**. History is retained; the existing published pointer remains unchanged until a separate explicit publish operation.
- **Idempotency:** operations use (tenant, schedule, actor, action, idempotency key) and refuse reuse with a different request. Replays of an already completed operation return the same receipt without duplicating versions/audit entries. Permission is rechecked on replay.
- **Audit:** all actions, including grant/revoke and stage/approve/publish/restore, require reasons and generate append-only audit events with a per-schedule SHA-256 hash chain. SQLite triggers prevent ordinary row UPDATE/DELETE of historical versions and audit records. This does **not** prevent a privileged database administrator dropping triggers or rewriting the SQLite file.
- **Single-writer transaction:** SQLite `BEGIN IMMEDIATE` serialises writes and rollback on failure. SQL queries are bound by exact tenant/schedule IDs. The process must not use client-supplied tenant values as a trusted identity.

## Concurrency example

An accepted options plan is at revision 1. Two planners independently stage alternative C4 proposals against revision 1. An authorised reviewer approves Proposal A to create revision 2. Approving Proposal B against revision 1 is **STALE_SOURCE**, not an opportunity to overwrite revision 2. A repeated approval with the *same* idempotency key returns the original receipt. If the reviewer later restores revision 1, revision 3 is newly created and can be published only after a distinct authorised publication decision.

## Distinct schedule modules (GRID-D021)

C5 stores revisions by `(organisation_id, schedule_id)` and `kind`; it does **not** treat a tenant's entire timetable collection as one compulsory solve. Approving an option-plan revision never changes an independently maintained examinations, invigilation, duties or sport timetable, nor does it publish an academic lesson timetable derived from the option plan. Cross-schedule read-only commitments must be explicitly linked and version-pinned in a later contract. There is no automatic multi-schedule cascade.

## Security/prod gaps before *any* school data

1. Replace trusted-in-process `Principal` with a reviewed server-only Veni Account token/session verification adapter, including issuer/audience/signature/expiry checks, revocation, MFA policies and explicit identity linking where needed. The Veni Account principal is identity only; Grid tenant membership/permission is a separate server source of truth.
2. Migrate SQLite semantics to versioned PostgreSQL migrations in the separately governed Veni Flow Supabase tenant environment; enforce RLS, deny direct table writes by ordinary clients, narrow service-role usage and tenant/organisation scoping for **every** operation. Validate SQLite/Postgres concurrency differences, isolation, failure handling, constraint races, retry semantics and transaction boundaries.
3. Separate the review receipt from the trusted acceptance state: a transient C4 `SnapshotRef(state='ACCEPTED')` exists only for testing the current C2 adapter. The real server must issue accepted versions only after completed, authenticated approval.
4. Implement persisted, encrypted, restricted retention for learner, staff and timetable data; secure backups and restore drills; immutable audit storage inaccessible for mutation by the application role, independent export and monitoring; POPIA security safeguards and breach procedures.
5. Implement a **separate academic placement acceptance and publication** flow (and optional explicit linked transaction), not implicit publication on options approval. Define permissions for source import, curricular changes, and linked read-only commitments.
6. Add tested authenticated API endpoints, CSRF protection where cookie-based, replay protections, rate-limits, audit reason `change → reason popup → confirm/cancel`, and negative authorization tests with real staging identities before enabling any button.
7. Add version history UI for concurrent viewers, conflict resolution, source stale banners, before/after diff, revalidation before publication and rollback recovery; no UI mock button may claim real approval now.

## How to reproduce the **reference**

```bash
python -m scripts.prepare_workspace
python -m pytest -q c5_tests
python -m scripts.run_c5_reference
```

Then open `c5-output/c5-approval-history.html`. The preview displays actual local SQLite reference audit and version receipts from the real C4 synthetic proof. No source code connects to a user account or publishes a live schedule.
