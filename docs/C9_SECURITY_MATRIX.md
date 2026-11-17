# C9 security and correctness checks

| Gate | Real executed test intended in isolated PG17 | Boundary not established |
|---|---|---|
| Signature | Generated RSA key signs actual JWT checked via C6 code | Live Supabase JWKS/key rotation |
| Revocation | Callback checks active token session on every request | Real managed Supabase session API |
| MFA | AAL1 checker token rejected before DB approval | Live MFA registration and step-up flow |
| Server route | Trusted registration selects DB school + schedule | Production route ownership/role credentials |
| School membership | Actual PostgreSQL ACTIVE membership read | Veni Flow production membership authority |
| Explicit grant | Exact proposal/approval grant enforced | Complete delegation/provisioning UI |
| Mathematical validation | Real `review_errors` checks O1 + C2 and 48/18 evidence | Independent verification inside DB or another service |
| Resource-policy integrity | Server-pinned C2 target fingerprint rejects modified teacher/room/time policy | Live authoritative school roster and policy store |
| Evidence lineage | C2 placement problem reconstructed from O1 options + server-pinned C2 target + proposed windows; full problem and source/target hashes compared | DB-native proof or signed service-to-service attestation |
| Candidate source | Current stored accepted O1 bytes and revision/hash rechecked | Final canonical hash scheme across languages |
| Staging | PENDING proposal with nine sections, 48 allocations, audit event | Production-grade trusted API/retention |
| Maker/checker | Different signed actor approves, original planner cannot | Live account/session and role IAM |
| Concurrent changes | C8 transaction CAS and idempotency preserved | Distributed API failures, storage replication |
| Publication | Approved options rev2, published pointer unchanged | Separate publish/rollback procedures |
| Client exposure | No HTTP API, no browser role, no public RPC | Network/API penetration test |
| Migration | No hosted Supabase SQL, PG17 disposable only | Actual Auth-managed staging migration/pgTAP |

**A reference integration is not a production-authenticated school approval system.**
