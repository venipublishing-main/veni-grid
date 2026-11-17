# C8 executed evidence matrix (disposable PostgreSQL ONLY)

| Protection | Database/CI test | Remaining production condition |
|---|---|---|
| Private RLS retained | Eight tables remain ENABLE+FORCE | Actual shared Supabase RLS/advisors |
| Client roles blocked | anon/authenticated/service_role have zero private schema rights and no C8 EXECUTE | Actual Supabase authenticator/role audit |
| Reader sees own school | Active member + exact VIEW grant sees only their timetable | Trusted verified actor ID passed from live Veni Auth |
| No membership / no grant | Unauthorized rows filtered to zero | Live membership lifecycle and revocation |
| Cross-school | Other tenant has no result and composite FKs stay enforced | Actual multi-tenant penetration tests |
| Owner view | Owner reads only its own school's schedules | Delegation/owner legal model acceptance |
| No direct writes | Reader/operator have no direct table UPDATE/INSERT | Privileged credential storage in server |
| Two-person approval | Proposer cannot approve own proposal | Trusted creator/reviewer audit across real sessions |
| MFA step-up | AAL1 test is refused | Real Supabase AAL2 enrollment and session check |
| Source freshness | Exact revision+SHA-256 compared within a transaction | C4 evidence binding and linked schedule revisions |
| Revision CAS race | Two physical PG connections → one success | Production load/timeout tests |
| Idempotency | Same request same receipt; modified replay denied | Distributed API retries, message queue behavior |
| History | Approved version inserted, audit appended, old snapshots immutable | Off-app audit export / backup restore drills |
| Separate publication | Approval doesn't change publication pointer | Authenticated, independently guarded publish / rollback transactions |
| Trusted source | Only synthetic server-created proposal seeded | Server-stage must run independent C4 review_errors |

**C8 grants no browser Data API access and contains NO production migration, user-authenticated API, billing or live school data. A positive test role simulating a server does not prove that real Veni sessions are trustworthy.**
