# C7 exact regression and security proof matrix

| Test family | What PostgreSQL actually does | What is NOT proved |
| --- | --- | --- |
| Engine and target | Connects to PostgreSQL 17 with exact `grid_c7_isolated` database guard | Actual hosted Veni staging or production |
| DDL boot | Parses and executes unchanged C6 `grid_private` DDL with a throwaway `auth.users` stub | Full Supabase-managed Auth compatibility/migration history |
| Every table | Inspects all eight table flags: RLS ENABLE + FORCE | Positive tenant-authorised RLS policies |
| Direct grants | `anon`, `authenticated`, `service_role` test roles lack Grid schema/object privileges | Correct real Supabase project role grants |
| Accidental grant | Grants temporary access and verifies RLS still returns zero rows/denies inserts | Protection from superuser, BYPASSRLS or malicious privileged writer |
| Tenant FKs | Cross-school schedule, grant, version, proposal, audit and operation links fail FK | A server-only membership oracle for actual Veni users |
| Identity FK | Unknown central `auth.users` UUID rejected | Verified JWT issuer, active session or MFA against live Account |
| Immutable history | Actual SQL triggers reject UPDATE/DELETE of version/audit; proposal content cannot mutate | Admin-grade immutable audit or backups |
| Optimistic revision CAS | First revision-1 update succeeds, stale second update changes zero rows | Full SQL review/approve authorization transaction |
| Concurrent writers | Two real PostgreSQL connections race for same source row: exactly one succeeds | Real web/API load and arbitrary transaction failure modes |
| Restore | New revision 3 can reproduce source content, prior versions remain, publication pointer stays unchanged | Production rollback side effects, notification, external distribution |
| Idempotency | Composite key duplication rejected | Replay of same request/response with a verified payload (C5 implementation still local SQLite) |
| Existing Grid | 619 inherited tests rerun without code changes | Full 1,500-learner academic solver, vendor parity, production readiness |

**Never mistake passing default-deny tests for complete school-data authorization.** No Grid client RLS policies, trusted PostgreSQL writer role, source/session verifier, APIs or migration history are introduced by C7.
