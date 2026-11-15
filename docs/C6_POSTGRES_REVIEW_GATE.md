# C6 PostgreSQL / Supabase draft security gate

**DDL status: UNAPPLIED, STATIC-REVIEWED ONLY.** The SQL file `db/review/c6_grid_private_schema.sql` is not a validated production migration, and no Supabase project was modified. The connected shared Veni staging project was inactive at the time of review.

## Data model and separation

- **Identity source:** Existing Veni Account Supabase `auth.users.id` only. No second authentication account table, no user-email matching, and no duplicate entitlements.
- **Tenant authority:** Grid-owned organisation membership references the central user UUID, separate from platform entitlements.
- **Schedule scope:** `(organisation_id, schedule_id)` composite keys and foreign keys on every grant, version, proposal, audit and idempotency record. Types distinguish `ACADEMIC_OPTIONS`, `ACADEMIC_LESSONS`, `EXAMINATIONS`, `INVIGILATION`, `DUTIES`, `SPORT` and `ROOMS`.
- **Historical records:** Prior accepted option versions and audit events are append-only by trigger in the proposal. A rollback must create a **new** version, never delete prior revisions. The C5 reference already demonstrates this transaction pattern locally.
- **Safe by default:** schema `grid_private` is NOT to be in Data API exposed schemas. Every table has `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`. `PUBLIC`, `anon` and `authenticated` table/schema/function/sequence access is revoked. There are intentionally NO client RLS policies, no frontend RPC and no `SECURITY DEFINER` function.
- **Separability:** All core keys and constraints live inside `grid_private` except the identity FK to `auth.users`; future separation is possible only with an explicitly designed stable identity federation, migration/reconciliation and complete regression review.

## What the SQL does not yet implement

There is NO runtime writer role, no service account or live API endpoint. There are no production approval/publish stored procedures and no server-side transaction context or audit archival service. Default deny may keep the tables inaccessible until a later permission-gated migration is accepted. This is intentional. A schema with RLS enabled is **not** proof that its eventual policies are correct.

It is prohibited to expose the Supabase `service_role` / secret key in the browser or use a `SECURITY DEFINER` function in `public` as a shortcut. Supabase's official docs distinguish PostgreSQL GRANTs from RLS and recommend operation-specific allow/deny testing and `supabase test db` with pgTAP. This gate follows those principles but has not executed a PostgreSQL test.

## Required verification before application

1. Confirm the actual Veni Account shared project and inventory currently active `auth`/`public` schemas, migrations, RLS and roles. The old Stage-2 website account migration has known historical continuity issues; reconcile them first.
2. Select a **disposable PostgreSQL/Supabase staging clone**; verify current Supabase docs and migration CLI version (`supabase --help`, `supabase migration new --help`) before naming a migration.
3. Apply a **reviewed versioned migration** only to that clone after explicit project selection. No direct production SQL mutations from this review branch.
4. Run PostgreSQL parse/DDL tests, pgTAP checks for every table and client role, and negative cross-tenant, stale-revision, maker/checker and idempotency transaction races. Verify that unauthenticated and ordinary authenticated clients cannot read any Grid table in the unexposed schema.
5. Provision a narrowly scoped server-only DB role after the token/session verifier and real Veni Flow membership authority are working. Never grant broad client write access just to make an API call succeed.
6. Run Supabase Security and Performance Advisors, reconcile all findings, prove backups/audit integrity, and document full rollback plan and POPIA retention before actual school data.
7. Obtain explicit authorisation to enable an approval API. The current standalone HTML controls remain inert.

**Only static 10-point SQL guardrail tests have executed now.** They check table names, composite foreign keys, default deny/RLS syntax, use of the central `auth.users` UUID and immutable-history intent. They are **not** a substitute for an actual PostgreSQL engine, RLS policy execution or production pen-test.

Official documentation consulted: https://supabase.com/docs/guides/auth/signing-keys ; https://supabase.com/docs/guides/database/postgres/row-level-security ; https://supabase.com/docs/guides/api/securing-your-api ; https://supabase.com/docs/guides/local-development/testing/overview .
