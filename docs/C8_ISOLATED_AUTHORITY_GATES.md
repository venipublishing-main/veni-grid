# Veni Grid C8 — positive school-scoped database controls and approval reference

**Status: executed only on disposable PostgreSQL 17 in GitHub Actions once the CI run passes. No Veni Supabase migrations. No live authentication or production approval.**

## Why this is a distinct milestone

C7 verified that PostgreSQL denies everybody access to the private Grid schema by default. C8 asks a different question: **can a server-side reader see only the particular school and schedules for which it has permission, and can the database execute a narrowly scoped two-person approval without allowing raw table mutation?**

This C8 pilot adds `db/c8/c8_isolated_policy_approval.sql` **after** the unchanged C6 private-schema DDL. It runs only when the actual database is `grid_c8_isolated` on PostgreSQL 17 as superuser `postgres` in a disposable GitHub service. It uses a synthetic `auth.users` stub, not a real Supabase Auth migration. No code goes into `supabase/migrations`.

## Trust and role model (critical)

- **One Veni Account:** identity is the existing Veni Supabase Auth UUID. Grid creates no second login or password storage. Veni Account entitlement is not a grant to view or manage a school schedule.
- **Separate school authority:** active Grid membership is required; ordinary members also need an explicit per-schedule `view` grant. A school owner may view that school's schedules but is not automatically allowed to approve without an *exact* approve grant in this new database procedure.
- **Read-only database role:** `grid_c8_reader` is NOLOGIN, NOSUPERUSER and NOBYPASSRLS, granted only specific SELECT privileges, with RLS predicates on exact active membership and schedule grants. Its RLS policies do not allow clients to change their `organisation_id` or use a guessed schedule ID to see another school's rows.
- **Approved operations only:** `grid_c8_operator` is another NOLOGIN/NOBYPASSRLS role without direct Grid table SELECT/INSERT/UPDATE grants. It may execute *only* the private C8 approval function (besides ordinary non-Grid system functions). `grid_c8_writer` is a third NOLOGIN/NOBYPASSRLS role owning that function and holding the minimum table rights needed to commit a version/audit transaction. `SECURITY DEFINER` uses an explicitly empty search path; the function owner is **not** a superuser or BYPASSRLS role. Browser roles `PUBLIC`, `anon`, `authenticated`, `service_role` have neither C8 function EXECUTE nor Grid schema USAGE.
- **Session context is not yet identity verification.** The PostgreSQL connection uses `grid.c8_actor_id` and `grid.c8_aal` custom settings, which are **forgeable by anyone holding the privileged server connection**. Thus the C8 operator and reader roles MUST remain inaccessible to browser clients and must only ever be assumed by a server that independently verifies the C6 JWT, active session, AAL2 status and current school membership. Those production connections are NOT implemented or tested in C8. These settings are not credentials and do not stand alone as a real security boundary.

## Actual C8 procedure: limited options-plan approval

`grid_private.c8_approve(organisation_id,schedule_id,proposal_id,expected_revision,expected_source_hash,reason,idempotency_key)` is a **reference function** for `ACADEMIC_OPTIONS` only:

1. Rejects absent trusted actor context, non-AAL2 assurance, inadequate reason or idempotency key.
2. Requires an active organisation membership and an exact `approve` grant for the selected schedule; owner status/entitlements do not substitute for the grant. A reviewer cannot approve a proposal created by the same actor.
3. Checks the idempotency record before attempting a revision update. A matching replay returns the same receipt; the same key with changed request is rejected. Permission is rechecked even for replays.
4. Takes a PostgreSQL row lock on the original school schedule and checks **both** expected revision and SHA-256. If another approval won, the second is stale. Cross-school foreign keys remain enforced.
5. Requires a PENDING proposal whose source version and hash match, verifies the JSONB payload hash, and then in one database transaction advances the accepted option head, inserts an immutable new version, marks the proposal APPROVED, appends a versioned audit entry, and records the idempotency receipt.
6. Leaves `published_revision` **untouched** and explicitly reports `timetable_published=false`. It does not approve a separate academic lesson timetable, invigilation, examinations, duties or sport schedule.

**Important validator boundary:** C8 does **not** independently execute the mathematical C4 option/teacher/room verifier inside SQL. The deliberately synthetic proposal is pre-seeded into the disposable database by a privileged test fixture. A real, trusted server-side staging operation must verify C4 evidence and source freshness before permitting a proposal into the database; never expose an arbitrary client staging function. A matching JSONB SHA-256 proves **integrity of stored bytes**, not the correctness of a school timetable.

## Executed tests and where claims stop

The GitHub workflow runs the unchanged 647 C1–C7 tests and 36 C8 test cases: **683 expected**. C8 includes four static safeguards and 32 actual PostgreSQL cases. The new SQL tests cover:

- Positive reader visibility at School Alpha and School Beta, current membership, exact view grants, other-school denials, owner-bound viewing and immediate membership revocation.
- No raw Grid table access for `grid_c8_operator`; the `anon`, `authenticated`, and `service_role` imitations cannot inherit operator/reader roles or invoke C8 approval. Actor GUC spoofing as an ordinary authenticated role still cannot read the private tables.
- Exact approval grant, two-person checks, AAL2 requirement, source revision/hash CAS, payload-hash consistency, idempotent replay/changed-payload refusal, immutable revisions and audit, and approval not publishing anything.
- Two genuinely concurrent PostgreSQL backend connections racing to approve two different proposals against revision 1: exactly one can commit revision 2, and the other is refused as STALE_SOURCE.

**NOT proved:** live Supabase Auth verification or key rotation; production MFA; authentic school memberships; user session revocation; actual PostgreSQL role credentials/service account; safe public HTTP API; independent C4 validation at staging; production-like Supabase migration history or security advisors after C8 SQL; staging publication/rollback procedures; off-database audit retention; POPIA safeguards; complete school scale.

## Reproduce within the isolated workflow

`.github/workflows/c8-isolated-approval.yml` starts one disposable `postgres:17` container with `grid_c7_isolated`. The existing C7 tests create/read their own C7 database. C8 creates a **separate** `grid_c8_isolated` database in the same container, after double safety guards `GRID_C7_DISPOSABLE_ONLY=YES` and `GRID_C8_DISPOSABLE_ONLY=YES` and checks actual database, localhost and superuser. Only then does it apply the unchanged C6 DDL plus new C8 SQL. It runs all 683 tests and produces a synthetic JSON/HTML receipt.

No SQL is sent to the connected Veni Publishing Supabase project (which was assessed read-only). It remains unchanged. A future C9 security gate must reconcile the shared Account migration history and prepare an approved, disposable **Supabase staging clone** for actual auth-managed roles, restricted server login, MFA/session verification, C4-staging evidence, approval/publish/rollback and RLS/pgTAP testing.
