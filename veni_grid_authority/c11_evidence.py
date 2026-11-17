"""C11 REVIEW: versioned, byte-exact *options evidence*, not authorisation.

Python's existing GRID-JSON-1 fingerprint and PostgreSQL's JSONB::text hash
can differ on the same semantic document. C11 preserves one explicit UTF-8
serialization, binds its hash to a single school schedule/source revision and
lets a disposable PostgreSQL 17 verifier hash those *same bytes*.

Neither a digest nor this plain-Python envelope authenticates an actor or
proves C4 mathematical correctness. C9/C8 approval and existing DB columns
are intentionally unchanged; C11 is not a migration or publication service.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from enum import Enum
from hashlib import sha256
from hmac import compare_digest
import json
import re
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from veni_grid_contract.handoff_common import fingerprint, normalise
from veni_grid_contract.option_design import option_errors
from veni_grid_contract.options_handoff import AcceptedOptions


CONTRACT_VERSION = "veni-grid.c11.options-evidence.v1"
SERIALIZER = "GRID-JSON-1"
MAX_CANONICAL_UTF8_BYTES = 4_000_000  # bounded prototype, not a school-scale promise
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class C11EvidenceRejected(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def grid_json_1(value: Any) -> str:
    """Exactly the historical GRID-JSON-1 *Python* serialization profile.

    This is deliberately not RFC 8785 / JCS. JSON object keys are sorted by
    Python; array order and numeric types remain significant. The generated
    UTF-8 bytes, never PostgreSQL JSONB::text, are the hash input.
    """

    def default(v):
        if isinstance(v, date):
            return v.isoformat()
        if isinstance(v, Enum):
            return v.value
        raise TypeError(f"Cannot serialize {type(v).__name__}")

    def has_nul(v):
        # PostgreSQL JSONB refuses U+0000, even when JSON-escaped. Do not
        # produce evidence that cannot survive the required SQL check.
        if isinstance(v, str):
            return '\x00' in v
        if isinstance(v, dict):
            return any(has_nul(k) or has_nul(item) for k,item in v.items())
        if isinstance(v, (list, tuple)):
            return any(has_nul(item) for item in v)
        return False

    try:
        normalized = normalise(value)
        if has_nul(normalized):
            raise ValueError("PostgreSQL JSONB cannot store U+0000")
        return json.dumps(normalized, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False, default=default)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise C11EvidenceRejected("GRID_JSON_1_UNSUPPORTED_VALUE") from exc


def _utf8(value: str) -> bytes:
    if not isinstance(value, str):
        raise C11EvidenceRejected("CANONICAL_TEXT_REQUIRED")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeError:
        raise C11EvidenceRejected("INVALID_UNICODE") from None
    if not 1 <= len(encoded) <= MAX_CANONICAL_UTF8_BYTES:
        raise C11EvidenceRejected("EVIDENCE_SIZE_OUT_OF_BOUNDS")
    return encoded


def _sha(value: str) -> str:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise C11EvidenceRejected("SHA256_FORMAT_REQUIRED")
    return value


def _uuid(value: str) -> str:
    try:
        actual = str(UUID(value))
        if actual != value:
            raise ValueError("Noncanonical UUID")
        return actual
    except (ValueError, TypeError, AttributeError):
        raise C11EvidenceRejected("SERVER_SCOPE_UUID_REQUIRED") from None


@dataclass(frozen=True)
class SourceBinding:
    """Server-selected scope; these fields are NOT authenticated by typing."""

    organisation_uuid: str
    schedule_uuid: str
    source_revision: int
    source_grid_json_1_sha256: str
    c4_validated_teaching_sha256: str

    def __post_init__(self):
        _uuid(self.organisation_uuid)
        _uuid(self.schedule_uuid)
        if type(self.source_revision) is not int or self.source_revision < 1:
            raise C11EvidenceRejected("POSITIVE_SOURCE_REVISION_REQUIRED")
        _sha(self.source_grid_json_1_sha256)
        _sha(self.c4_validated_teaching_sha256)


@dataclass(frozen=True)
class EvidenceV1:
    """Portable bytes + checksum; NOT proof of signer, validity or approval."""

    contract_version: str
    serializer: str
    canonical_json: str
    canonical_utf8_length: int
    sha256: str


def _candidate(candidate: AcceptedOptions) -> AcceptedOptions:
    if not isinstance(candidate, AcceptedOptions):
        raise C11EvidenceRejected("TYPED_OPTIONS_REQUIRED")
    if option_errors(candidate.demand, candidate.plan):
        raise C11EvidenceRejected("INVALID_OPTIONS_WITNESS")
    return candidate


def create_evidence(candidate: AcceptedOptions, *, binding: SourceBinding) -> EvidenceV1:
    """Bind a previously independently reviewed C4 candidate into one scope.

    This does not perform the C4/C2 proof. The trusted caller must supply the
    validated teaching fingerprint from the independently reviewed C4 result.
    """
    if not isinstance(binding, SourceBinding):
        raise C11EvidenceRejected("SERVER_SOURCE_BINDING_REQUIRED")
    candidate = _candidate(candidate)
    value = {
        "contract_version": CONTRACT_VERSION,
        "serializer": SERIALIZER,
        "schedule_kind": "ACADEMIC_OPTIONS",
        "scope": asdict(binding),
        "accepted_options_grid_json_1_sha256": fingerprint(candidate),
        "accepted_options": normalise(candidate),
    }
    canonical = grid_json_1(value)
    data = _utf8(canonical)
    return EvidenceV1(contract_version=CONTRACT_VERSION, serializer=SERIALIZER,
                      canonical_json=canonical, canonical_utf8_length=len(data),
                      sha256=sha256(data).hexdigest())


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise C11EvidenceRejected("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _reject_constant(_value: str):
    raise C11EvidenceRejected("INVALID_JSON_CONSTANT")


def verify_evidence(evidence: EvidenceV1, *, binding: SourceBinding) -> AcceptedOptions:
    """Independent Python byte/shape/review-envelope verification, no writes."""
    if not isinstance(evidence, EvidenceV1) or not isinstance(binding, SourceBinding):
        raise C11EvidenceRejected("EVIDENCE_AND_SERVER_BINDING_REQUIRED")
    if evidence.contract_version != CONTRACT_VERSION or evidence.serializer != SERIALIZER:
        raise C11EvidenceRejected("UNSUPPORTED_EVIDENCE_PROFILE")
    data = _utf8(evidence.canonical_json)
    if type(evidence.canonical_utf8_length) is not int or evidence.canonical_utf8_length != len(data):
        raise C11EvidenceRejected("CANONICAL_BYTE_LENGTH_MISMATCH")
    if not compare_digest(_sha(evidence.sha256), sha256(data).hexdigest()):
        raise C11EvidenceRejected("CANONICAL_BYTES_SHA256_MISMATCH")
    try:
        document = json.loads(evidence.canonical_json, object_pairs_hook=_reject_duplicate_keys,
                              parse_constant=_reject_constant)
    except C11EvidenceRejected:
        raise
    except (ValueError, TypeError):
        raise C11EvidenceRejected("INVALID_CANONICAL_JSON") from None
    if grid_json_1(document) != evidence.canonical_json:
        raise C11EvidenceRejected("NONCANONICAL_GRID_JSON_1")
    if not isinstance(document, dict) or set(document) != {
        "contract_version", "serializer", "schedule_kind", "scope",
        "accepted_options_grid_json_1_sha256", "accepted_options",
    }:
        raise C11EvidenceRejected("INVALID_ENVELOPE_SHAPE")
    if (document["contract_version"] != CONTRACT_VERSION
            or document["serializer"] != SERIALIZER
            or document["schedule_kind"] != "ACADEMIC_OPTIONS"):
        raise C11EvidenceRejected("ENVELOPE_KIND_OR_PROFILE_MISMATCH")
    if document["scope"] != asdict(binding):
        raise C11EvidenceRejected("SERVER_SOURCE_SCOPE_MISMATCH")
    try:
        candidate = AcceptedOptions.model_validate(document["accepted_options"])
    except (ValueError, TypeError, ValidationError):
        raise C11EvidenceRejected("INVALID_ACCEPTED_OPTIONS_PAYLOAD") from None
    _candidate(candidate)
    # Pydantic defaults/normalisation must not silently change a received
    # payload. A hash of a syntactically valid but different model is refused.
    if grid_json_1(candidate) != grid_json_1(document["accepted_options"]):
        raise C11EvidenceRejected("MODEL_NORMALISATION_MISMATCH")
    if document["accepted_options_grid_json_1_sha256"] != fingerprint(candidate):
        raise C11EvidenceRejected("ACCEPTED_OPTIONS_FINGERPRINT_MISMATCH")
    return candidate
