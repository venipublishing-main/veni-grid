# C4 Review/Acceptance/Publication Boundaries — draft for production implementation

C4 creates **proposal documents** only. These are not school records and cannot approve, accept, or publish a timetable. The user-facing HTML deliberately disables its approval action and states the missing server-side security and authority requirements.

## Proposed production workflow (not implemented)

1. **Preview:** Create a separate candidate against a trusted source schedule ID/revision/hash. Read optional external timetable commitments only when explicitly chosen. Run independently checked O1 and C2 calculations without modifying any accepted source.
2. **Review:** Store a persistent immutable candidate and complete before/after event, section, learner-choice, teacher and room diff. Source of truth must be an authenticated organisation-owned store. Record actor and purpose; avoid logging learner personal data in public CI.
3. **Authorised approval:** At submission, re-check that the user is permitted to approve *this schedule namespace*, with least privilege. Confirm tenant, resource/subject constraints, current-source revision/hash, all linked read-only reference versions and independent validation results.
4. **Atomic write:** Transactional compare-and-swap on current revision, deterministic idempotency key, append-only audit event and a new accepted version. If any version changed, refuse and require regeneration/review; do not partially publish.
5. **Independent publication:** User separately chooses Publish after approval. Publish only this independently requested timetable; maintain earlier version and a rollback workflow. No default regeneration of academic/exam/invigilation/duties/sport calendars.
6. **Retention/POPIA:** Controlled school tenant access, data minimisation, bounded retention, secure secret handling, account/log protections, and authorised exports. Real learner data must not enter the public synthetic repository.

## Current C4 review receipt

`preview_id` is a deterministic lineage label, **not a credential, signature or token**. `source_revision`, `source_sha256`, `proposed_o1_sha256` and `proposed_c2_candidate_sha256` are integrity values. `changed_request_ids` identifies precisely which compulsory learner-subject assignments moved option blocks. `FamilyDiff` gives school-user subject-level before/after, section counts and moved requests. `review_errors()` re-checks the source, option witness, the complete C1 placement witness and the receipt values, but **does not authenticate actors, confirm latest server revision or authorise any write**.

All current authority-related fields are fixed to `SIMULATED_IN_MEMORY_ONLY`, `REQUIRES_AUTHENTICATED_REVIEW`, `saved=NO`, and `publication=NOT_GRANTED`. No public API should permit changing those fields based merely on client-provided text.
