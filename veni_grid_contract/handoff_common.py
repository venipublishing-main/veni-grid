"""Draft handoff identity and provenance. Pure functions; no store, auth or solver.

The fingerprint profile is GRID-JSON-1 (defined in docs/HANDOFF_CONTRACT.md),
not a claim to implement RFC 8785. Fingerprints detect content changes, not authorship.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, Field

from .models import ID
from .primitives import ContractModel, Finding, Positive


class HandoffError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def normalise(value: Any) -> Any:
    """Use complete typed values; UTC-normalise datetime fields before hashing.

    Array order is significant. Mapping key order is not. Model defaults are included.
    String values are not interpreted as dates. Revalidation precedes this operation.
    """
    if isinstance(value, BaseModel):
        return normalise(value.model_dump(mode="python"))
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise HandoffError("NAIVE_INSTANT", "Timestamps require an explicit offset")
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
    if isinstance(value, dict):
        if not all(isinstance(k, str) for k in value):
            raise HandoffError("INVALID_HASH_KEY", "Only string keys are allowed")
        return {k: normalise(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalise(v) for v in value]
    # date and Enum serialization is handled by JSON's explicit fallback below.
    return value


def fingerprint(value: Any) -> str:
    from datetime import date
    from enum import Enum
    def default(v):
        if isinstance(v, date):
            return v.isoformat()
        if isinstance(v, Enum):
            return v.value
        raise TypeError(f"Cannot fingerprint {type(v).__name__}")
    data = json.dumps(normalise(value), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False, default=default)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def stable_id(kind: str, *parts: str) -> str:
    """Namespaced deterministic identity; revisions are deliberately NOT part of IDs."""
    name = json.dumps(["veni-grid-handoff-1", kind, *parts], separators=(",", ":"))
    return f"{kind}:{uuid5(NAMESPACE_URL, name)}"


class SnapshotRef(ContractModel):
    organisation_id: ID
    schedule_id: ID
    revision: Positive
    schema_version: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    origin: Literal["GRID", "MANUAL", "NORMALISED_IMPORT"]
    state: Literal["DRAFT", "ACCEPTED", "PUBLISHED", "RETIRED"]


def snapshot_ref(payload: BaseModel, *, organisation_id: str, schedule_id: str,
                 revision: int, origin: str = "GRID", state: str = "ACCEPTED") -> SnapshotRef:
    """Fixture/helper constructor, NOT a trusted acceptance or publishing action."""
    return SnapshotRef(organisation_id=organisation_id, schedule_id=schedule_id,
                       revision=revision, schema_version=payload.schema_version,
                       content_sha256=fingerprint(payload), origin=origin, state=state)


def check_source(ref: SnapshotRef, payload: BaseModel, organisation_id: str,
                 target_schedule_id: str) -> None:
    if ref.organisation_id != organisation_id:
        raise HandoffError("CROSS_ORGANISATION_SOURCE", ref.schedule_id)
    if ref.schedule_id == target_schedule_id:
        raise HandoffError("SOURCE_IS_TARGET", target_schedule_id)
    if ref.state not in ("ACCEPTED", "PUBLISHED"):
        raise HandoffError("SOURCE_NOT_ACCEPTED", ref.state)
    if ref.schema_version != payload.schema_version:
        raise HandoffError("SOURCE_SCHEMA_MISMATCH", ref.schedule_id)
    if ref.content_sha256 != fingerprint(payload):
        raise HandoffError("SOURCE_CONTENT_MISMATCH", ref.schedule_id)


def freshness_errors(expected: list[SnapshotRef], authoritative: list[SnapshotRef]) -> list[Finding]:
    """Only meaningful when 'authoritative' comes from a trusted current registry.

    This preflight is not an atomic compare-and-swap; that belongs in a future writer.
    """
    result: list[Finding] = []
    def key(ref): return (ref.organisation_id, ref.schedule_id)
    for label, refs in (("expected", expected), ("current", authoritative)):
        if len({key(r) for r in refs}) != len(refs):
            result.append(Finding(code="DUPLICATE_SNAPSHOT", detail=label))
    current = {key(r): r for r in authoritative}
    for old in expected:
        new = current.get(key(old))
        if new is None:
            result.append(Finding(code="SOURCE_NOT_AVAILABLE", detail=old.schedule_id))
        elif new != old:
            result.append(Finding(code="STALE_SNAPSHOT", detail=old.schedule_id))
    return result


class EntityMapping(ContractModel):
    source_kind: str
    source_id: ID
    source_component: ID | None = None
    target_kind: str
    target_id: ID


class HandoffReceipt(ContractModel):
    schema_version: Literal["0.4.0-draft"] = "0.4.0-draft"
    handoff_id: ID
    adapter_id: Literal["OPTIONS_TO_LESSONS", "EXAMS_TO_COVERAGE"]
    adapter_version: Literal["0.4.0-draft"] = "0.4.0-draft"
    source: SnapshotRef
    target_schedule_id: ID
    target_model_version: Positive
    target_schema_version: str
    config_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    output_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    readiness: Literal["INPUT_VALIDATED_NOT_SOLVED"] = "INPUT_VALIDATED_NOT_SOLVED"
    mappings: list[EntityMapping]
    limitations: list[str]


def receipt(adapter: str, ref: SnapshotRef, config: BaseModel, output: BaseModel,
            target_id: str, mappings: list[EntityMapping], limitations: list[str]) -> HandoffReceipt:
    digest = fingerprint(config)
    return HandoffReceipt(
        handoff_id=stable_id("handoff", adapter, ref.organisation_id, ref.schedule_id,
                             str(ref.revision), ref.content_sha256, target_id, digest),
        adapter_id=adapter, source=ref, target_schedule_id=target_id,
        target_model_version=output.model_version, target_schema_version=output.schema_version,
        config_sha256=digest, output_sha256=fingerprint(output), mappings=mappings,
        limitations=limitations)


def receipt_errors(rec: HandoffReceipt, adapter: str, source: SnapshotRef, config: BaseModel,
                   output: BaseModel, target_id: str) -> list[Finding]:
    """Check the entire receipt identity, independently of the adapter implementation."""
    findings=[]
    expected_id=stable_id("handoff",adapter,source.organisation_id,source.schedule_id,
                         str(source.revision),source.content_sha256,target_id,fingerprint(config))
    if rec.handoff_id!=expected_id or rec.adapter_id!=adapter:
        findings.append(Finding(code="HANDOFF_IDENTITY_MISMATCH",detail="Adapter/receipt identity"))
    if rec.source!=source or rec.config_sha256!=fingerprint(config):
        findings.append(Finding(code="RECEIPT_LINEAGE_MISMATCH",detail="Source/config binding"))
    if (rec.target_schedule_id,rec.target_model_version,rec.target_schema_version)!=(
        target_id,output.model_version,output.schema_version):
        findings.append(Finding(code="RECEIPT_TARGET_MISMATCH",detail="Target/schema binding"))
    if rec.output_sha256!=fingerprint(output):
        findings.append(Finding(code="OUTPUT_FINGERPRINT_MISMATCH",detail="Output content"))
    return findings
