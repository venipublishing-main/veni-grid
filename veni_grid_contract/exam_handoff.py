"""Fixed normalised exams -> coverage demand. No native ACTion/aSc importer.

The source owns venue reservations. Coverage adds staff claims only. Staffing
minima are explicit input policy, not jurisdiction-specific defaults.
"""
from __future__ import annotations
from datetime import timedelta
from typing import Literal
from pydantic import Field, model_validator
from .models import ID
from .primitives import (ContractModel, Positive, NonNegative, CapacityResource,
    Interval, ResourceClaim, Finding, usage_errors, unique_errors)
from .coverage import (CoverageProblem, CoverageWitness, FixedSession,
    CoverageDemand, coverage_errors)
from .handoff_common import (SnapshotRef, HandoffError, HandoffReceipt, EntityMapping,
    check_source, stable_id, fingerprint, receipt, receipt_errors)


class ExamRecord(ContractModel):
    id: ID
    paper_id: ID
    label: str = Field(min_length=1)
    venue_id: ID
    supervision_interval: Interval
    candidate_count: Positive


class ExamSnapshot(ContractModel):
    schema_version: Literal["0.4.0-draft"] = "0.4.0-draft"
    venues: list[CapacityResource] = Field(min_length=1)
    sessions: list[ExamRecord] = Field(min_length=1)


class CoverageBandPolicy(ContractModel):
    key: ID
    start_offset_minutes: NonNegative
    end_offset_minutes: Positive
    role: str = Field(min_length=1)
    minimum_staff: Positive
    eligible_staff_ids: list[ID] = Field(min_length=1)

    @model_validator(mode="after")
    def proper_band(self):
        if self.end_offset_minutes <= self.start_offset_minutes:
            raise ValueError("Coverage band must have positive length")
        if len(set(self.eligible_staff_ids)) != len(self.eligible_staff_ids):
            raise ValueError("Duplicate staff eligibility")
        return self


class SessionCoveragePolicy(ContractModel):
    source_session_id: ID
    bands: list[CoverageBandPolicy] = Field(min_length=1)


class CoverageTargetConfig(ContractModel):
    organisation_id: ID
    schedule_id: ID
    model_version: Positive
    selected_session_ids: list[ID] = Field(min_length=1)
    staff: list[CapacityResource] = Field(min_length=1)
    policy_id: ID
    policy_revision: Positive
    policies: list[SessionCoveragePolicy] = Field(min_length=1)


class ExamHandoff(ContractModel):
    schema_version: Literal["0.4.0-draft"] = "0.4.0-draft"
    source_ref: SnapshotRef
    source: ExamSnapshot
    target: CoverageTargetConfig


class ExamHandoffResult(ContractModel):
    schema_version: Literal["0.4.0-draft"] = "0.4.0-draft"
    request: ExamHandoff
    problem: CoverageProblem
    source_reservations: list[ResourceClaim]
    receipt: HandoffReceipt


def session_id(req: ExamHandoff, eid: str) -> str:
    return stable_id("session", req.source_ref.organisation_id, req.source_ref.schedule_id,
                     req.target.schedule_id, eid)


def source_reservations(req: ExamHandoff) -> list[ResourceClaim]:
    """Derived solely from fixed exam facts, including unselected source sessions."""
    venues = {v.id: v for v in req.source.venues}
    claims = []
    for e in sorted(req.source.sessions, key=lambda s: s.id):
        v = venues.get(e.venue_id)
        if v is None: raise HandoffError("UNKNOWN_EXAM_VENUE", e.id)
        if v.kind != "SPACE" or v.unit != "SEATS":
            raise HandoffError("UNSUPPORTED_VENUE_UNIT", e.venue_id)
        if e.candidate_count > v.capacity:
            raise HandoffError("EXAM_OVER_VENUE_CAPACITY", e.id)
        claims.append(ResourceClaim(
            id=stable_id("reservation", req.source_ref.organisation_id, req.source_ref.schedule_id,e.id,e.venue_id),
            schedule_id=req.source_ref.schedule_id,entity_id=e.id,resource_id=e.venue_id,
            interval=e.supervision_interval,
            units=e.candidate_count if v.sharing=="CUMULATIVE" else 1))
    return claims


def _check(req: ExamHandoff) -> list[ResourceClaim]:
    src, cfg = req.source, req.target
    check_source(req.source_ref,src,cfg.organisation_id,cfg.schedule_id)
    duplicates = unique_errors(src.sessions,"exams")+unique_errors(src.venues,"venues")+unique_errors(cfg.staff,"staff")
    if duplicates: raise HandoffError("DUPLICATE_SOURCE_ID", "; ".join(e.detail for e in duplicates))
    if any(s.kind!="PERSON" for s in cfg.staff): raise HandoffError("INVALID_STAFF_TYPE","Coverage staff must be people")
    if {s.id for s in cfg.staff}&{v.id for v in src.venues}: raise HandoffError("RESOURCE_ID_COLLISION","Staff and venue IDs overlap")
    selection=set(cfg.selected_session_ids); exams={e.id for e in src.sessions}
    if len(selection)!=len(cfg.selected_session_ids) or not selection<=exams:
        raise HandoffError("INVALID_EXAM_SELECTION","Unknown or duplicate session")
    policy_ids=[p.source_session_id for p in cfg.policies]
    if len(set(policy_ids))!=len(policy_ids) or set(policy_ids)!=selection:
        raise HandoffError("COVERAGE_POLICY_INCOMPLETE","One explicit policy per selected exam required")
    staff={s.id for s in cfg.staff}
    for policy in cfg.policies:
        if len({b.key for b in policy.bands})!=len(policy.bands): raise HandoffError("DUPLICATE_POLICY_BAND",policy.source_session_id)
        for b in policy.bands:
            if not set(b.eligible_staff_ids)<=staff: raise HandoffError("UNRESOLVED_STAFF_IDENTITY",b.key)
    claims=source_reservations(req)
    errors=usage_errors(src.venues,claims)
    if errors: raise HandoffError("INVALID_FIXED_EXAM_SNAPSHOT","; ".join(e.code for e in errors))
    return claims


def build_exam_handoff(request: ExamHandoff) -> ExamHandoffResult:
    request=ExamHandoff.model_validate(request.model_dump(mode="json"))
    reservations=_check(request)
    src,cfg=request.source,request.target
    exams={s.id:s for s in src.sessions}; policies={p.source_session_id:p for p in cfg.policies}
    sessions=[];demands=[];mappings=[]
    # Elapsed offsets use UTC to remain correct across offset changes.
    from datetime import timezone
    for eid in sorted(cfg.selected_session_ids):
        e=exams[eid];sid=session_id(request,eid)
        sessions.append(FixedSession(id=sid,venue_id=e.venue_id,interval=e.supervision_interval))
        mappings.append(EntityMapping(source_kind="EXAM_SESSION",source_id=eid,target_kind="FIXED_SESSION",target_id=sid))
        for band in policies[eid].bands:
            did=stable_id("coverage",cfg.organisation_id,request.source_ref.schedule_id,cfg.schedule_id,eid,band.key)
            start=e.supervision_interval.start.astimezone(timezone.utc)
            demands.append(CoverageDemand(id=did,session_id=sid,role=band.role,
                interval=Interval(start=start+timedelta(minutes=band.start_offset_minutes),
                                  end=start+timedelta(minutes=band.end_offset_minutes)),
                minimum_staff=band.minimum_staff,eligible_staff_ids=band.eligible_staff_ids))
            mappings.append(EntityMapping(source_kind="COVERAGE_POLICY_BAND",source_id=eid,source_component=band.key,
                                           target_kind="COVERAGE_DEMAND",target_id=did))
    p=CoverageProblem(problem_id=cfg.schedule_id,model_version=cfg.model_version,
        schedule_id=cfg.schedule_id,resources=[*src.venues,*cfg.staff],sessions=sessions,demands=demands)
    # With no proposed staff yet, a staffing COVERAGE_GAP is expected. All other
    # findings (including DEMAND_COVERAGE_GAP) are errors in the handoff input.
    empty=CoverageWitness(problem_id=p.problem_id,model_version=p.model_version,duties=[])
    structural=[f for f in coverage_errors(p,empty) if f.code!="COVERAGE_GAP"]
    if structural: raise HandoffError("INVALID_COVERAGE_INPUT","; ".join(f.code for f in structural))
    rec=receipt("EXAMS_TO_COVERAGE",request.source_ref,cfg,p,cfg.schedule_id,mappings,
        ["Input is normalised data, not a native ACTion/aSc file importer.",
         "Venue reservations belong to the source; staff duties must not reacquire them.",
         "Staffing policy is explicit and synthetic in fixtures; no regulatory minima are assumed.",
         "Staffing feasibility has not been solved."])
    result = ExamHandoffResult(request=request,problem=p,source_reservations=reservations,receipt=rec)
    return ExamHandoffResult.model_validate_json(result.model_dump_json())


def exam_handoff_errors(result: ExamHandoffResult) -> list[Finding]:
    """Independent reverse check of dates, venues, demand and reservation ownership."""
    result=ExamHandoffResult.model_validate(result.model_dump(mode="json"))
    req,p,rec=result.request,result.problem,result.receipt
    errors=[]
    def bad(code,detail): errors.append(Finding(code=code,detail=detail))
    try: expected_claims=_check(req)
    except HandoffError as exc:
        bad(exc.code,exc.detail);return errors
    errors.extend(receipt_errors(rec,"EXAMS_TO_COVERAGE",req.source_ref,req.target,p,req.target.schedule_id))
    if rec.source!=req.source_ref or rec.config_sha256!=fingerprint(req.target): bad("RECEIPT_LINEAGE_MISMATCH","Exam source/policy")
    if rec.output_sha256!=fingerprint(p): bad("OUTPUT_FINGERPRINT_MISMATCH","Coverage input")
    if (p.problem_id,p.schedule_id,p.model_version)!=(req.target.schedule_id,req.target.schedule_id,req.target.model_version):
        bad("TARGET_IDENTITY_CHANGED","Coverage target")
    if p.resources!=[*req.source.venues,*req.target.staff]: bad("TARGET_CONTEXT_CHANGED","Venue/staff catalogue")
    if result.source_reservations!=expected_claims: bad("SOURCE_RESERVATIONS_CHANGED","Missing, added, reassigned or modified source claims")
    source={e.id:e for e in req.source.sessions};actual={s.id:s for s in p.sessions}
    if len(actual)!=len(p.sessions) or set(actual)!={session_id(req,eid) for eid in req.target.selected_session_ids}:
        bad("SESSION_SET_CHANGED","Selected examinations")
    for eid in req.target.selected_session_ids:
        e=source[eid];s=actual.get(session_id(req,eid))
        if not s or s.venue_id!=e.venue_id or s.interval!=e.supervision_interval:
            bad("FIXED_EXAM_FACT_CHANGED",eid)
    # Compare policy projections semantically, not using the builder.
    from datetime import timezone
    expected=[]
    for policy in req.target.policies:
        start=source[policy.source_session_id].supervision_interval.start.astimezone(timezone.utc)
        for b in policy.bands:
            expected.append((session_id(req,policy.source_session_id),b.role,
                start+timedelta(minutes=b.start_offset_minutes),start+timedelta(minutes=b.end_offset_minutes),
                b.minimum_staff,tuple(b.eligible_staff_ids)))
    observed=[(d.session_id,d.role,d.interval.start.astimezone(timezone.utc),d.interval.end.astimezone(timezone.utc),
               d.minimum_staff,tuple(d.eligible_staff_ids)) for d in p.demands]
    if sorted(expected)!=sorted(observed): bad("COVERAGE_POLICY_CHANGED","Coverage bands, minima or eligibility")
    empty=CoverageWitness(problem_id=p.problem_id,model_version=p.model_version,duties=[])
    errors += [e for e in coverage_errors(p,empty) if e.code!="COVERAGE_GAP"]
    keys=[(m.source_kind,m.source_id,m.target_kind,m.target_id) for m in rec.mappings]
    if len(keys)!=len(set(keys)): bad("DUPLICATE_LINEAGE_MAPPING","Exam mappings")
    for eid in req.target.selected_session_ids:
        if ("EXAM_SESSION",eid,"FIXED_SESSION",session_id(req,eid)) not in keys:
            bad("EXAM_LINEAGE_LOST",eid)
    expected_maps=set()
    for eid in req.target.selected_session_ids:
        expected_maps.add(("EXAM_SESSION",eid,None,"FIXED_SESSION",session_id(req,eid)))
    for policy in req.target.policies:
        for b in policy.bands:
            did=stable_id("coverage",req.target.organisation_id,req.source_ref.schedule_id,
                          req.target.schedule_id,policy.source_session_id,b.key)
            expected_maps.add(("COVERAGE_POLICY_BAND",policy.source_session_id,b.key,"COVERAGE_DEMAND",did))
    actual_maps={(m.source_kind,m.source_id,m.source_component,m.target_kind,m.target_id) for m in rec.mappings}
    if actual_maps!=expected_maps or len(rec.mappings)!=len(expected_maps):
        bad("LINEAGE_MANIFEST_MISMATCH","Exam/policy traceability")
    return errors
