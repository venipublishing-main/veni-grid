# C9: Veni Account signed identity → independently validated C4 → restricted PostgreSQL option approval

**Status: research integration on disposable PostgreSQL 17 only. NO real Veni Auth, authenticated API, production Supabase migration, live school data, or timetable publication.**

## Why C9 is a meaningful new gate

C6 verified synthetic JWT signatures and defined a trusted session callback. C7 executed the private schema. C8 added a tenant-aware server-only reader and a restricted PostgreSQL approval function, but used **forgeable PostgreSQL connection settings** for the actor and MFA assurance. Worse, its original SQL test fixture seeded a JSONB placeholder saying it had been validated, without running C4 validation during staging.

C9 connects the existing verifier, **real C4 independent mathematical review**, current PostgreSQL school membership and exact per-schedule grants in one in-process service adapter. The candidate stores actual `AcceptedOptions` (48 allocations, nine sections) rather than an arbitrary approval label, and approval happens under a *different* verified RSA-signed actor. The original C4 result includes 18 independently valid C2 teaching events; accepting options **does not** approve the lesson timetable.

## Server-owned trust sequence

1. The future server maintains a `ServerScheduleRegistration` mapping an internal route key to one PostgreSQL `organisation_uuid` and `schedule_uuid`, original domain O1/C2 source IDs and a **server-approved C2 teaching-resource policy fingerprint**. An untrusted client never supplies a school UUID or authoritative resource policy from user metadata.
2. C6 `IdentityGate` validates the access token against a trusted *server-supplied* pinned JWKS, issuer, audience and active-session callback. C9 checks current **database membership and exact propose grant BEFORE processing the C4 document**, then rechecks at commit.
3. C4 `review_errors()` checks the proposed option design and C2 teacher, room and lesson witness. C9 additionally pins the supplied school's C2 target to the trusted server registration and **reconstructs the exact C2 placement problem** from the proposed options, chosen windows, original resource policy and C4 candidate attempt. The reported C2 placement problem and its source/target/output fingerprints must match that reconstruction, so a hard-valid witness for another timetable cannot be passed off as evidence for these options. The original accepted source remains unchanged.
4. C9 starts an SQL transaction under the server-only `grid_c8_writer` role, takes a row lock, checks exact revision and source bytes/hash, independently checks `AcceptedOptions`, and saves an immutable PENDING proposal with a versioned audit event and idempotency receipt. This is **only staging**, not approval or publication.
5. A second C6 verified JWT token is checked with action `approve`, including AAL2 step-up in the token and a current active-session lookup. The server again checks current membership. It sets PostgreSQL actor/AAL context and invokes the **unchanged C8** private `grid_private.c8_approve()` function under NOLOGIN `grid_c8_operator`.
6. The database rechecks exact approve grant, maker/checker separation, source version CAS, integrity hash and idempotency, creating a new immutable accepted options revision and audit event. **`published_revision` stays NULL**. Independent academic lesson/invigilation/exam/sport/duty timetables are untouched.

## Critical security qualifications

- The signed JWTs are **genuine RSA cryptographic signatures with invented keys**, but the trusted JWKS/session callbacks are **offline test doubles**, and the currently active Veni Supabase project is only accessed read-only. C9 has no HTTP route, cookie session, CSRF/rate-limits, key cache, production Veni JWKS provider, current session API integration or real MFA enrollment.
- The tests connect as the **disposable PostgreSQL `postgres` superuser** and assume narrow NOLOGIN roles with `SET LOCAL ROLE`. This is not a suitable production server credential. Anyone who obtains a role capable of setting `grid.c8_actor_id` can spoof the actor if trusted-server credential isolation fails. An actual production role and stored-procedure model remain subject to review.
- C9 independently validates a C4 candidate in Python before staging, but **C8 SQL itself does not rerun C4**. It relies on the server-only route and immutable DB proposal; securing that boundary is the point of this test, not proof of an independently tamper-proof trust service.
- The authoritative C2 target fingerprint is currently supplied by the **invented test server registry**. A live school resource/teaching-policy snapshot, its version history, protected updates and server-side retrieval are still unimplemented. An authenticated user must not be allowed to register their own permissive target.
- Accepted source content is checked against the **C4 Pydantic fingerprint**; the existing C8 approval function stores a **PostgreSQL JSONB::text digest** for its accepted revision. C9 recognises both *only when the underlying accepted content exactly matches*. This needs a canonical versioned cross-language hash contract before a production release. Neither hash authenticates an actor or proves mathematical correctness.
- Both staging and approval are currently for `ACADEMIC_OPTIONS` only, not general timetable publication. There is no trusted account/tenant provisioning UI, actual production database migration, staged membership federation, joint change, automatic rollback or production retention.

## Regression and test matrix

- 683 inherited Grid tests (C1–C8) stay untouched.
- 23 new C9 tests: 5 local source/security guards + 18 real PG17 integration cases. These verify actual C4 witness staging, complete options contents, true PostgreSQL membership and exact propose grant, second signed AAL2 reviewer, no publication, cross-school denial, forged signature/issuer, revoked sessions, AAL1 refusal, maker/checker, stale source, forged review receipt, idempotent stage, changed replay, scope refusal, grant revocation, **server-policy substitution refusal and unbound C2 problem refusal**.
- Dedicated C9 GitHub Action must run all **706 tests** and regenerate the true C4→C9→C8 result under isolated PG17. Do not claim CI succeeded until the full run and receipt are actually inspected.

## Next explicit production gates

1. Reconcile the Veni Account foundation migration history and secure an approved Supabase staging clone with actual Auth-managed roles; do not apply C6/C8 SQL to the current shared Veni project.
2. Build a least-privileged, secret-managed server identity/service with verified live JWKS rotation, session revocation, real AAL2 MFA, school membership from the approved authority and strong request-level rate-limit/CSRF requirements.
3. Replace forgeable custom-context assumptions, finalise cross-language hashes and bind one complete C4 validated proposal (including evidence digest and independent teacher/room claims) to an immutable review record. Implement separately authenticated publication and rollback and off-app audit backup.
4. Test two-person approval under actual tenant permissions in disposable Supabase (including pgTAP, advisors, reloads and fault injection), and retain GRID-D021 independent timetables. Explicit permission is required before real rollout or use of identifiable learners.
