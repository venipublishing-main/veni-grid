# C5 verification matrix (local reference only)

The reviewed C5 reference uses an isolated local SQLite database for each test and actual C4-generated synthetic proposal evidence. Nothing here confirms real OAuth, Supabase RLS or safe operations over production school data.

| Capability | Automated evidence |
|---|---|
| C4 evidence is genuinely validated | Actual CP-SAT option/teaching candidate used; stage refuses altered review receipts |
| Staging does not approve or publish | Accepted source revision and publication pointer remain unchanged |
| Default deny | Unknown members, reviewers and ungranted actions refused |
| Tenant isolation | Same `schedule_id` in another tenant does not share versions or grants |
| Namespace isolation | Approval of academic options cannot change invigilation or exams |
| Permission delegation/revocation | Owner-granted narrow scope; revoke takes effect immediately, including on replay |
| Two-person control | Proposer cannot approve own C4 candidate |
| Stale source safety | Stale proposals and old browser revisions rejected without partial writes |
| Idempotency | Duplicate requests return same receipt, conflict if request payload differs |
| Immutable versions | SQLite UPDATE/DELETE trigger failure and prior revision still retrievable |
| Separate publish | Approved revision not published until independently permissioned operation |
| Rollback | Earlier revision copied into **new** version; published pointer remains unchanged until separately republished |
| Append-only audit | Typed actions, reasons, chained SHA-256 receipts, verified by independent recomputation |
| No unguarded bootstrap | The ability to create an owner/tenant is disabled by default |
| No live integrations | No HTTP routes, real school data, real token parser, real production DB or external delivery |

The full Grid regression suite additionally guards C1/Q1/Q2/Q3/O1/C2/C3/C4 from source changes. GitHub CI must generate the same reference result from a fresh checkout; check status and actual artifacts before marking remote validation complete.
