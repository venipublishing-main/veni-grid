# C10 — Veni Account identity transport preflight (decision pending)

**Status: synthetic, local policy REFERENCE ONLY. No identity architecture chosen, no browser/API integration, no OAuth exchange, no hosted Supabase writes, no school data, no timetable approval or publication.**

## Why this step is necessary

Veni's ratified DEC-013 architecture requires one Veni Account identity and central
entitlements across independently built Spheres. It **does not** make a Veni
Account holder a member of any school, or confer permissions for an individual
academic-options, academic-lessons, examinations, invigilation, duty, sport or
rooms timetable.

The Website/Reserve integration work still has two identity candidates requiring
platform-owner ratification:

1. **Shared Auth:** each Sphere uses the same Veni Supabase Auth issuer and
   canonical `auth.users.id`. A login in a different browser origin does not
   automatically mean a silent, secure or currently active session in Grid.
2. **OAuth/PKCE handoff:** an upstream identity provider exchanges an
   authorization code with PKCE and returns a server-validated identity. OAuth
   authorization alone is **not** authentication: the eventual design must
   establish an authenticated issuer/subject through OIDC or an equivalent
   independently verified identity assertion. Only an explicit, verified,
   exactly one-to-one `issuer + subject → central Veni Account UUID` link may
   resolve that external identity. Matching an email, display name, profile
   metadata or payment entitlement can never establish the link.

Neither candidate is activated by this PR, and the reference cannot decide
between them. The C6/C9 signed-Supabase-JWT verifier remains unchanged.

## Preflight contract

`veni_grid_authority/c10_account_preflight.py` is an additive, offline
server-bound policy model. Its `approved_transport=None` default **refuses
every request**. Its only two explicitly configured test modes are
`SHARED_AUTH` and `OAUTH_HANDOFF`. The synthetic test harness supplies
invented session assertions and replaces all external lookups with in-memory
callbacks.

For either candidate, every request must pass **all** gates:

1. Exact configured transport, pinned HTTPS issuer and audience, and a trusted
   server verifier's fresh assertion. The assertion dataclass is not a
   credential, and a browser may never create or provide it directly.
2. Current session is still active; authentication expiry is bounded; the
   server-verifier callback must have checked cryptographic provenance,
   audience and protocol-specific anti-replay/state/nonce/PKCE protections.
   The reference itself does **not** perform any live verification or exchange.
3. For shared Auth, the verified subject is the canonical central Veni UUID.
   For an OAuth handoff, a dedicated server-owned resolver finds exactly one
   **active, verified, issuer/subject-bound** link to that UUID. Zero links,
   duplicate links, revoked links or mismatched identifiers fail closed.
4. The central account is currently active; this is separate from both a
   current session and school membership.
5. A **server-owned C9 schedule registration** selects one organisation and
   schedule. Current membership in that organisation is mandatory.
6. An exact per-schedule and per-action Grid grant is mandatory. `approve`
   requires AAL2. C10 preflight only models `view`, `propose` and `approve`,
   and cannot publish a timetable.

Every unexpected verifier, link, session, account, membership or grant lookup
failure causes refusal. Passing all gates returns a `ScopedPreflight` value
for diagnostic purposes, **not a portable authorisation token**. An actual C9
stage or C8 approval must independently reauthenticate and recheck relevant
permissions inside its own transaction. In particular, this PR does **not**
modify C9 to accept a fabricated `VerifierAssertion` or an OAuth subject.

## Existing live-system observations (read-only, 17 November 2026)

- The active Website Supabase project has existing account/Arcana tables and
  historical migrations but no verified live Grid schema or central school
  membership service. A `public.profiles` name already exists; one cannot
  assume Sphere schemas can be copied into `public` without reconciliation.
- The Reserve staging project is separate; the Performance development
  project remains paused. A shared account plan must not conflate a Sphere's
  business-tenancy schema or rights with the Veni Account namespace.
- Website/Reserve drafts demonstrate candidate flows in synthetic environments,
  including a cross-origin browser test, but do not themselves ratify
  production SSO or an OAuth authority. No hosted auth configuration, migration,
  secret, account or policy was changed during this audit.

These observations must be rechecked at the moment of any future hosted work.

## Readiness ledger

| Gate | Status | Owner / next proof |
| --- | --- | --- |
| Single Veni Account + sphere-specific authority | Ratified principle | DEC-013; retain separation |
| Choose shared Auth **or** OAuth/PKCE handoff | **BLOCKED — unratified** | Website/Reserve platform-owner decision |
| Deterministic transport-neutral rejection policy | Synthetic pass | C10's 29 focused tests |
| Shared Auth key rotation, active session, MFA/AAL2 | **NOT CONNECTED** | Veni Account identity owner, trusted server tests |
| OAuth issuer/subject proof, PKCE/state/nonce, consent and one-to-one link | **NOT IMPLEMENTED** | If OAuth is chosen: identity handoff specification and tests |
| Central account lifecycle, school membership source | **NOT CONNECTED** | Veni account and Veni Flow/organisation authority owners |
| Real schedule grants and separate maker/checker | Disposable PostgreSQL evidence only | C8/C9 production authority design |
| Reconciled hosted schema, least-privilege server roles, RLS security | **NOT APPLIED** | Approved disposable Supabase staging clone |
| Canonical hashes, C4 resource provenance and rollback audit | **NOT PRODUCTION READY** | Grid C9 successor design |
| Live publication, real school personnel/learner data | **NOT AUTHORIZED** | Separate later permissions and POPIA review |

## How to verify

From the reviewed Python environment after installing the repo's extras:

```bash
python -m scripts.run_ci
python -m pytest -q c10_tests
```

`run_ci` proves the preserved C1 source identity and its original 423 tests;
the C10 focused suite executes 29 additional parameterized synthetic cases.
The existing C9 GitHub workflow separately runs the inherited 706 tests and
disposable PostgreSQL staging evidence. A successful C10 workflow does not
claim any live authentication, hosted migration or school-scale performance.

## Precise next engineering dependency

Obtain the Website/Reserve team's ratified **identity transport and canonical
account-subject contract**, including session validation, account-link lifecycle
if applicable, account deletion/retention, delegated Sphere permission rules,
CSRF and rate limits. Only then design a *trusted server* adaptor to C9, run
isolated end-to-end contract tests, and separately request permission for an
approved disposable Supabase staging clone. Do not enable either transport or
interpret a C10 `ScopedPreflight` as authority in the interim.
