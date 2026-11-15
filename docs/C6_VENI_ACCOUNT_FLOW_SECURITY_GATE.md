# Veni Grid C6 — Shared Veni Account identity, distinct Grid authority

**Status:** additive C6 v0.1.0 REVIEW CANDIDATE. Real cryptographic JWT verification with entirely synthetic identities has been executed. The PostgreSQL schema is an **unapplied review design**; there is no production authentication, Data API, approval API or real school data migration.

## Canonical architecture recovered from live project sources

The 3 November 2026 **RATIFIED Veni Platform — Sphere Repository, Account & Entitlement Architecture v0.1** (DEC-013) says: one Veni Account, multiple independently built Spheres, central entitlement authority and trusted backend enforcement. A GitHub repository per substantial Sphere is an engineering boundary, **not a duplicate user account**. The website's actual `assets/js/veni-account.js` uses `window.VENI_SUPABASE` and `supabase.createClient(config.url, config.publishableKey)`, and its original account migration references `auth.users(id)` for profiles and entitlements. Do not create `grid_users`, maintain a second password database or infer account linkage from emails.

A central entitlement answers *may this account use the Grid feature?* It does not answer *may this person approve timetable X at school Y?* School-specific membership and per-schedule grants are a separate **Veni Flow** authority. A website login cannot grant school authority merely because the account is signed in, paid, an owner of an unrelated Sphere or says `role=admin` in user-editable metadata.

The connected Veni Publishing staging Supabase project was **INACTIVE** when inspected. No schema change, SQL execution, new project, organisation, user or secret has been created. The current architecture can use a dedicated `grid_private` schema in a shared Veni backend, with composite tenant/schedule keys and explicit export boundaries, if and only if the platform team confirms that consolidation plan. Extracting Grid to its own project later would require an explicit verified identity federation and migration, not an accidental second login.

## Verified identity gate (new additive Python module)

`veni_grid_authority.identity_gate.IdentityGate` verifies a **Supabase Auth access token** using a trusted pinned project issuer (`https://<project>.supabase.co/auth/v1`), pinned audience (`authenticated`), explicitly allowlisted asymmetric signature algorithms (`RS256`, `ES256`), matching unique `kid` from trusted server-fetched JWKS, valid `sub` and `session_id` UUIDs, required signed claims, and valid expiry/issuance bounds.

It rejects `HS256`/`none`, token-supplied `jku`, `x5u`, embedded public keys, unknown or duplicated `kid`, unrecognised roles, `is_anonymous=true`, expired/future/stale claims and overlong tokens. It requires an **active-session lookup** supplied by the server, because a validly signed token may not be revocation-fresh. The supplied `active_session` and `trusted_jwks` callbacks are offline test doubles today; a production implementation must supply fresh trusted Supabase Auth/session data and key-rotation handling.

`approve`, `publish`, `restore` and `grant` require `aal2` MFA step-up in this candidate; `view` and `propose` require a valid signed active `aal1` or stronger session. This stronger profile will deliberately BLOCK approvals until the actual Veni Account MFA deployment is ready and independently tested. It must not be weakened by a frontend setting.

`bind_grid_principal` then selects an organisation **from a trusted server route** and performs an independent current membership check before producing a C5 `Principal`. It ignores all organisation, role, entitlement and email claims from user-editable metadata. The unchanged C5 authority store still checks exact schedule grants and maker/checker separation. The `Principal` dataclass is not by itself a security credential and must never be created from an arbitrary request body.

## Trust flow (draft, not wired to a web endpoint)

1. Browser signs into Veni Account using its existing Supabase Auth project. Only a short-lived access token reaches a trusted Grid server over HTTPS. No secret/service key reaches the browser.
2. The Grid server validates issuer, audience, signing key and current session. High-risk actions require MFA AAL2.
3. The server resolves the selected Veni Flow school by a trusted route, **does not read tenant authority from the JWT**, and checks active organisation membership.
4. For each operation, a separate Grid authorisation service verifies exact schedule permissions and checks relevant independent timetable snapshots.
5. Future PostgreSQL transactions compare the current accepted revision and its hash, bind an idempotency key, append an audit entry, and separately require approval and publication. No operation can silently alter a separate exam/invigilation/sport/duty schedule.

## Verified locally

27 new focused tests pass: real ephemeral RSA and EC signed tokens, forged or malformed tokens, MFA, revocation failure, different issuer/audience, metadata spoofing, missing membership, unavailable JWKS/session checker, plus static checks on the proposed private schema. A real synthetic RSA JWT probe outputs `c6-output/c6-security-summary.json` and an understandable read-only HTML explainer. No signing key, access token or real user identifier is saved in those output files.

The C1–C5 592-test suite was reconstructed from previous public source archives; all **619 = 592 + 27** tests passed locally. Prior Grid solver code was not changed for C6.

## Still blocked — explicit production gate

- The existing Veni Account staging project must be active and its **actual** Auth signing-key configuration and session-revocation guarantees read from the account owner; no invented JWKS endpoint may be trusted.
- Review shared Supabase migration history: the Veni website ledger records manually applied account foundation SQL and a historical duplicate migration. C6 must **not** overwrite or duplicate account/Arcana migration history.
- The candidate `db/review/c6_grid_private_schema.sql` is NOT a migration file in `supabase/migrations` and was NOT applied. Actual PostgreSQL syntax, RLS allow/deny tests and concurrency must be executed against an isolated staging clone, then security advisors must be reviewed before any deployment.
- Establish a non-bypass, least-privileged database role and transaction-only trusted service, validate issuer/key-rotation/session lookups, add rate limits and CSRF where cookie-based, and run independent cross-tenant, cross-schedule and stale-version API tests.
- Verify actual production authority/privilege integration with the platform's consolidation policy; do not infer a user's school role from a free/premium entitlement.
- Explicitly approve account-data deletion retention and POPIA requirements before introducing identifiable school pupils or staff.

**No live account, school tenant, migration, production API, approval, publication or rollback action has been performed in C6.**
