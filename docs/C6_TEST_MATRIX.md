# C6 automated assurance test inventory

| Test gate | Executed evidence | Still missing |
|---|---|---|
| RSA/ES256 JWT verification | Real generated key pairs, valid signed tokens, 17 Python identity tests | Actual Veni Auth JWKS rotation, current sessions |
| Algorithm/kid/header attacks | HS256, wrong kid, duplicate kid, token-supplied URL and embedded key refused | Real compromised-key response/drills |
| Claims | issuer, audience, required `sub`/session, lifetimes, role, anonymity rejected | Production token version variations |
| MFA | AAL1 allowed for proposals; AAL2 required for approve/publish/restore/grant | Veni Account AAL2 enrollment/step-up UX |
| Revocation | Simulated active-session oracle denies revoked or offline lookup | Real Supabase sessions integration |
| Tenant trust | Checked server membership required; user metadata ignored | Real Veni Flow membership provider |
| Private schema | 10 static DDL tests: RLS enabled/forced, REVOKE, composite FKs, append-only triggers, no browser RPC | Actual PostgreSQL DDL and pgTAP/RLS execution |
| Existing Grid regressions | 592 inherited + 27 C6 = 619 local | GitHub CI must reproduce separately |
| Live actions | None | Authenticated API, migrations, approvals, publication, audit backup |

All synthetic test keys are ephemeral and never serialized to the test artifacts.
