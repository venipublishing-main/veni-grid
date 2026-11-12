"""Validated staffing-only before/after review. Never applies or publishes changes.

Versions must be supplied by an authoritative store in a future application.
This module is executable contract evidence, NOT a concurrency/authentication layer.
"""
from __future__ import annotations
from collections import Counter
from typing import Literal
from pydantic import Field
from .models import ID
from .primitives import ContractModel, Interval, ResourceClaim, Finding, usage_errors
from .coverage import CoverageProblem, CoverageWitness, coverage_errors, duty_minutes
from .handoff_common import (SnapshotRef, fingerprint, stable_id, freshness_errors)
from .exam_handoff import ExamHandoffResult, exam_handoff_errors


class CoverageState(ContractModel):
    schema_version: Literal["0.4.0-draft"] = "0.4.0-draft"
    problem: CoverageProblem
    witness: CoverageWitness


class DutyFieldChange(ContractModel):
    duty_id: ID
    field: Literal["resource_id", "session_id", "role", "interval"]
    before: str | Interval
    after: str | Interval


class StaffingReviewRequest(ContractModel):
    schema_version: Literal["0.4.0-draft"] = "0.4.0-draft"
    job_id: ID
    handoff: ExamHandoffResult
    baseline_ref: SnapshotRef
    baseline: CoverageWitness
    candidate: CoverageWitness
    mutable_duty_ids: list[ID] = Field(min_length=1)
    allowed_fields: list[Literal["resource_id"]] = Field(default_factory=lambda:["resource_id"], min_length=1, max_length=1)
    declared_changes: list[DutyFieldChange]
    # Claims intentionally absent: callers cannot hide bookings by omitting them.


class StaffingReviewResult(ContractModel):
    schema_version: Literal["0.4.0-draft"] = "0.4.0-draft"
    job_id: ID
    status: Literal["BLOCKED", "VALIDATED_PROPOSAL_NOT_APPLIED"]
    findings: list[Finding]
    actual_changes: list[DutyFieldChange]
    complete_target_claims: list[ResourceClaim]
    source_reservations: list[ResourceClaim]
    duty_minutes_by_person: dict[str,float]


def derive_staff_claims(p: CoverageProblem,w: CoverageWitness) -> list[ResourceClaim]:
    """Derive every staff duty, including untouched duties; never add venue claims."""
    return [ResourceClaim(id=stable_id("claim",p.schedule_id,d.id,d.resource_id),
        schedule_id=p.schedule_id,entity_id=d.id,resource_id=d.resource_id,interval=d.interval)
        for d in sorted(w.duties,key=lambda x:x.id)]


def derive_changes(before: CoverageWitness,after: CoverageWitness) -> list[DutyFieldChange]:
    old={d.id:d for d in before.duties};new={d.id:d for d in after.duties};out=[]
    for did in sorted(set(old)&set(new)):
        for field in ("resource_id","session_id","role","interval"):
            left,right=getattr(old[did],field),getattr(new[did],field)
            if left!=right: out.append(DutyFieldChange(duty_id=did,field=field,before=left,after=right))
    return out


def review_staffing_change(request: StaffingReviewRequest,
                           authoritative_current_refs: list[SnapshotRef]) -> StaffingReviewResult:
    request=StaffingReviewRequest.model_validate(request.model_dump(mode="json"))
    p=request.handoff.problem
    errors=list(exam_handoff_errors(request.handoff))
    def bad(code,detail): errors.append(Finding(code=code,detail=detail))
    ref=request.baseline_ref
    source_ref=request.handoff.request.source_ref
    if (ref.organisation_id,ref.schedule_id)!=(source_ref.organisation_id,p.schedule_id):
        bad("WRONG_TARGET_SNAPSHOT","Target organisation/schedule")
    expected_state=CoverageState(problem=p,witness=request.baseline)
    if ref.schema_version!=expected_state.schema_version or ref.content_sha256!=fingerprint(expected_state):
        bad("BASELINE_CONTENT_MISMATCH","Baseline must be the actual target snapshot")
    if ref.state not in ("ACCEPTED","PUBLISHED"): bad("BASELINE_NOT_ACCEPTED",ref.state)
    for w in (request.baseline,request.candidate):
        if (w.problem_id,w.model_version)!=(p.problem_id,p.model_version):
            bad("WRONG_TARGET_RESULT","Baseline/candidate model identity")
    errors += freshness_errors([source_ref,ref],authoritative_current_refs)
    before_ids=[d.id for d in request.baseline.duties];after_ids=[d.id for d in request.candidate.duties]
    if len(set(before_ids))!=len(before_ids) or len(set(after_ids))!=len(after_ids): bad("DUPLICATE_DUTY","Before/after IDs")
    if set(before_ids)!=set(after_ids): bad("UNAUTHORISED_DUTY_SET_CHANGE","Staffing-only review cannot add/remove duties")
    if len(set(request.mutable_duty_ids))!=len(request.mutable_duty_ids) or not set(request.mutable_duty_ids)<=set(before_ids):
        bad("INVALID_MUTABLE_SLICE","Unknown/duplicate selected duties")
    actual=derive_changes(request.baseline,request.candidate)
    for change in actual:
        if change.duty_id not in request.mutable_duty_ids or change.field not in request.allowed_fields:
            bad("OUT_OF_SCOPE_CHANGE",f"{change.duty_id}/{change.field}")
    # Compare full before/after values, not just a caller-declared list of changed IDs.
    declared=Counter(fingerprint(c) for c in request.declared_changes)
    observed=Counter(fingerprint(c) for c in actual)
    if declared!=observed: bad("CHANGE_MANIFEST_MISMATCH","Declared changes do not match actual complete before/after snapshots")
    errors += coverage_errors(p,request.candidate)
    claims=derive_staff_claims(p,request.candidate)
    # Full target claims + source-owned room bookings exactly once.
    errors += usage_errors(p.resources,[*request.handoff.source_reservations,*claims])
    return StaffingReviewResult(job_id=request.job_id,
        status="BLOCKED" if errors else "VALIDATED_PROPOSAL_NOT_APPLIED",
        findings=errors,actual_changes=actual,complete_target_claims=claims,
        source_reservations=request.handoff.source_reservations,
        duty_minutes_by_person={} if errors else duty_minutes(request.candidate))
