# C11 — exact-byte, versioned options proposal evidence

**Status: review-only engineering reference, tested against disposable PostgreSQL 17. Not a live Supabase migration, account integration, proposal stager, approval function or timetable publisher.**

## The C9 interoperability problem

C1/C4 handoff fingerprints use the existing Python **GRID-JSON-1** profile:
sorted object keys, compact separators, `ensure_ascii=False`, UTC-normalised
datetimes, included Pydantic defaults and SHA-256 of the resulting UTF-8 bytes.
C8's review database instead hashes PostgreSQL **`jsonb::text`**, where the
database may normalize representations and remove input whitespace or key
order. Thus two truthful SHA-256 strings can refer to semantically equal
options but be **different bytes**.

The signed C9 bridge currently accepts the known historical schemes only
after independently comparing the **actual** prior source contents. That
transition safeguard is retained. C11 introduces a future-compatible,
versioned byte representation without changing C8's storage or pretending an
existing accepted revision was retroactively rehashed.

## V1 contract — one exact UTF-8 byte stream

`veni_grid_authority.c11_evidence.create_evidence()` receives:

- A typed, independently options-validated `AcceptedOptions` object. Its
  proposed C4 lesson witness must already have been independently checked by
  the trusted staging service; **C11 hashing is not the C4/C2 review**.
- A **server-owned** `SourceBinding` containing an exact organisation UUID,
  schedule UUID, current accepted source revision, existing GRID-JSON-1 source
  content fingerprint and C4-validated teaching witness fingerprint.

The resulting JSON envelope contains precisely:

```json
{
  "contract_version": "veni-grid.c11.options-evidence.v1",
  "serializer": "GRID-JSON-1",
  "schedule_kind": "ACADEMIC_OPTIONS",
  "scope": {
    "organisation_uuid": "<server-selected UUID>",
    "schedule_uuid": "<server-selected UUID>",
    "source_revision": 1,
    "source_grid_json_1_sha256": "<64 lowercase hex characters>",
    "c4_validated_teaching_sha256": "<64 lowercase hex characters>"
  },
  "accepted_options_grid_json_1_sha256": "<64 lowercase hex characters>",
  "accepted_options": { "schema_version": "0.4.0-draft", "demand": {}, "plan": {} }
}
```

The sample above is a **shape illustration only**, not a valid candidate.
There is no undefined "hash of the same JSON" operation: the digest is
**SHA-256 of exactly the emitted UTF-8 text**. The envelope's own byte length
and digest are stored alongside it in `EvidenceV1`. V1 is purpose-built for
Grid and is **not RFC 8785/JCS**. Future serializer versions must have new
version identifiers and migration tests; never silently rewrite V1 bytes.

The independent Python verifier rejects noncanonical text even if an attacker
recomputes its digest, duplicate JSON keys, invalid options witnesses, changed
source/schedule/review identifiers, tampered byte length or hash, extra fields,
unsupported protocol/kind and changed typed-model normalisation. The source
and target are not inferred from client JSON. The byte stream is bounded to
4,000,000 bytes. U+0000 is explicitly unsupported because PostgreSQL JSONB
cannot represent it; the earlier C1 fingerprint code is not altered.

## Disposable PostgreSQL evidence

`db/c11/c11_isolated_hash_gate.sql` can execute **only** as `postgres` on a
PostgreSQL 17 database named exactly `grid_c11_isolated`, with an explicit
`grid.c11_disposable_only = YES` session gate. No client roles are granted
schema usage or function execution; the function is `SECURITY INVOKER`, not a
privileged web RPC.

The C11 test-only `grid_c11.verify_options_evidence_v1` function takes both
the exact canonical text and its `jsonb` equivalent, SHA-256, byte count and
the independently expected school/schedule/source/review identifiers. It:

1. SHA-256 hashes **the supplied original text converted to UTF-8**, rather
   than reserializing `jsonb`;
2. Compares the parsed JSONB payload with the stored JSONB document;
3. Enforces the V1 envelope kind, structural checks and exactly scoped source;
4. Fails closed on mismatched bytes, semantic content, revision or school.

PostgreSQL **does not independently prove Python canonicality or O1/C4
mathematical validity**. The trusted Python verifier and independent C4
review must run before a future privileged staging write. JSONB's semantic
equality cannot recover duplicate keys or erased whitespace; this is why
the canonical original text must also be retained if C11 is adopted.

## Test gate

Local, with reviewed Python dependencies:

```bash
python -m scripts.run_ci
python -m pytest -q c11_tests/test_c11_evidence.py
```

The independent C11 GitHub workflow starts a fresh, isolated PostgreSQL 17
container; it runs all **44 C11 cases** (29 local + 15 real database tests)
and reruns a genuine synthetic C4 proposal: 48 compulsory requests, nine
proposed sections, 18 independently valid teaching occurrences. A concise
`c11-output/c11-byte-parity-receipt.json` is archived; it contains no tokens,
database credentials, real account identifiers or private school inputs.

The existing C9 workflow separately reruns all 706 inherited security and
solver tests. None of these tests is a production release authorization.

## Explicit later migration gate

1. Design a reviewed immutable storage extension retaining **both** canonical
   bytes and the parsed JSONB candidate, envelope version, exact scoped hashes
   and a safe readback path. PostgreSQL must hash the original bytes itself.
2. Develop dual-read / no-overwrite handling for C8's historical
   `jsonb::text` hash revisions; the new V1 digest may **not** simply replace
   `head_sha256` or `payload_sha256` in already approved records.
3. Couple C9's validated C4/O1/C2 evidence to the immutable row and its
   exact source revision inside the trusted transaction. Keep maker/checker,
   AAL2, tenant and exact schedule permission independent of hashing.
4. Review least-privilege roles, RLS, audit backup, canonicalization evolution
   and rollback on an **explicitly approved disposable Supabase clone**, only
   after the Veni Account project architecture is settled.
5. Apply nothing to live projects and publish no timetable without separate
   authority and school-data/POPIA review.

**C11 is a content-integrity and replay-scope foundation; it never grants
identity, organisation membership, approval or publication.**
