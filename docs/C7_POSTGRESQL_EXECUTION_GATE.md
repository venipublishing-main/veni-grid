# Veni Grid C7 — Real isolated PostgreSQL 17 security execution

**Status: review-only, disposable database execution; NO Veni Supabase project writes.**

## Purpose and architecture

C6 supplied a private `grid_private` schema reviewed only as SQL text. C7 runs **that unchanged exact SQL** on a freshly provisioned PostgreSQL 17 database in GitHub Actions, using a minimal `auth.users` **test stub** and disposable `anon`, `authenticated`, and `service_role` roles. The database is always named `grid_c7_isolated`; a guard checks the actual database name, executing role and major server version **before any DDL**. A separate environment switch must explicitly affirm `GRID_C7_DISPOSABLE_ONLY=YES`. The service is deleted when the CI job terminates.

This does **not** reuse or clone user records, credentials, sessions, migrations, organisation memberships, or data from any Veni Account Supabase project. The connected project was inactive at the C6 preflight. No project activation, schema migration or real-data import was authorised or performed here.

## What real PostgreSQL tests prove

- PostgreSQL 17 truly parses and executes the unchanged reviewed C6 SQL, creating all eight private Grid tables.
- Every table has **RLS enabled and forced**, with **zero client policies**; anonymous, authenticated and service-role **test imitations** have no schema/table/function privileges.
- An authenticated role cannot read Grid schedule records. If someone accidentally grants it private-schema `USAGE` and table `SELECT` for a test transaction, RLS still returns **zero** rows. An accidental `INSERT` grant still does not permit a new organisation row.
- Foreign keys reject using School Alpha's organisation ID to reference School Beta's schedules or staff membership across grants, versions, proposals, idempotency and audit rows.
- Invalid or nonexisting central-user foreign keys are rejected. No email-based identity linkage exists.
- Triggers reject in-place `UPDATE` or `DELETE` of accepted-version and audit history. A proposal's content cannot be rewritten after staging; a separate state transition remains possible.
- Idempotency keys have a database-level composite uniqueness constraint; this **does not itself** implement complete request-payload replay logic, which remains a trusted application responsibility (C5 reference).
- An optimistic revision compare-and-swap accepts one update and rejects the stale second. A test with two **genuine simultaneous PostgreSQL connections** verifies only one writer wins a competing revision 1 → 2 update.
- Creating revision 3 as a copy of revision 1 leaves revision 2 available and leaves publication unchanged until a separate operation.

## Critical proof limits

The SQL has **no production grant policies, trusted server runtime writer, or approval/publish RPC**. These tests do **not** demonstrate authenticated Veni Account login, live session revocation, tenant-scoped positive RLS permissions, two-person approval on PostgreSQL, correct SHA calculation inside the DB, full C5 idempotent transactions on PostgreSQL, audit immutability against a superuser, or a production security review. `FORCE RLS` is bypassed by PostgreSQL superusers / `BYPASSRLS` roles and is only a defense-in-depth layer, not a substitute for privileged role controls.

The `auth.users` object is deliberately a **minimal disposable stub**, not Supabase's actual managed Auth schema. The three test roles are disposable imitations, not production auth roles, so these results do not establish that a shared live Supabase configuration has equivalent grants or policies.

## Next before actual live staging or school data

1. Confirm the named Veni staging project and agree who controls its migration history; do not resume an inactive or ambiguous project automatically.
2. Create an approved disposable **Supabase staging clone** with actual Auth-managed migrations. Reconcile the website's historical account foundation and duplicate migration before generating an official Supabase CLI migration.
3. Implement a reviewed, server-only, least-privilege write/approval design. Provide **trusted live Veni Account session verification**, explicit school membership, exact schedule grant, MFA step-up and maker/checker protections. Never authorise Grid using a browser-provided `organisation_id` or an impersonatable custom GUC.
4. Exercise actual tenant-bound RLS allow/deny, stale-source approval CAS, idempotency replay, concurrent writers, rollback and audit on PostgreSQL with restricted roles. Check Supabase security/performance advisors, least-privileged function EXECUTE and Data API visibility.
5. Run backup/restore drills and appropriate POPIA minimisation, retention and account-deletion reconciliation before handling real learners/staff.
6. Keep academic options, academic teaching, exams, invigilation, duties, sport and rooms independently versioned and published (GRID-D021). Do not enable UI Approve/Publish actions before explicit authorisation.

## Reproduce

The review workflow `.github/workflows/c7-isolated-postgres.yml` provisions the disposable `postgres:17` service, installs pinned `psycopg[binary]==3.2.12`, regenerates Grid synthetic fixtures, runs the inherited 619 tests plus 28 C7 tests, and writes a safety-boundary receipt. No `supabase db push`, hosted project URL or production credentials are used. The results are archived as GitHub Actions artifacts (retention limited) and backed up to the canonical Veni Grid Drive folder.

**No migration file was named or submitted to `supabase/migrations` in this step.** The required real Supabase migration later must be generated using the then-current CLI and reviewed against the actual destination's migration history. Refer to [Supabase current RLS](https://supabase.com/docs/guides/database/postgres/row-level-security) and [Data API security](https://supabase.com/docs/guides/api/securing-your-api) documentation.
