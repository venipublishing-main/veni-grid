"""Unequal-frequency options handoff using explicit occurrence-level alignment.

Every occurrence is either explicitly aligned with a sync key or explicitly
independent (null). No padded lessons, lost curriculum or inferred block pairing.
"""
from __future__ import annotations
from collections import defaultdict
from typing import Literal
from pydantic import Field

from .models import (ID, ResourceKind, Activity, Demand, Offering, Event, PlacementDomain,
                     ResourceRequirement, ParticipationRequest, RuleStrength, RuleSource)
from .core_v1 import CoreProblem, LocatedResource, Location, core_problem_errors
from .placement_v04 import SameStart
from .options_handoff import AcceptedOptions, LessonTemplate, LessonTargetConfig
from .option_design import option_errors
from .handoff_common import SnapshotRef, check_source, fingerprint, stable_id, HandoffError, EntityMapping
from .primitives import ContractModel, Positive, Finding


class OccurrenceBinding(ContractModel):
    section_id: ID
    occurrence_key: ID
    candidate_start_ids: list[ID] = Field(min_length=1)
    sync_key: ID | None  # REQUIRED even when null: deliberate standalone placement.


class FlexibleTarget(LessonTargetConfig):
    bindings: list[OccurrenceBinding] = Field(min_length=1)
    resources: list[LocatedResource] = Field(min_length=1)
    locations: list[Location] = Field(default_factory=list)
    alignment_semantics: Literal["EXPLICIT_START_ONLY"] = "EXPLICIT_START_ONLY"


class FlexibleOptionsRequest(ContractModel):
    schema_version: Literal["1.0.0-rc1"] = "1.0.0-rc1"
    source_ref: SnapshotRef
    source: AcceptedOptions
    target: FlexibleTarget


class FlexibleReceipt(ContractModel):
    schema_version: Literal["1.0.0-rc1"] = "1.0.0-rc1"
    source: SnapshotRef
    adapter_id: Literal["OPTIONS_TO_LESSONS_FLEX"] = "OPTIONS_TO_LESSONS_FLEX"
    config_sha256: str
    output_sha256: str
    target_schedule_id: ID
    target_model_version: Positive
    mappings: list[EntityMapping]
    readiness: Literal["INPUT_VALIDATED_NOT_SOLVED"] = "INPUT_VALIDATED_NOT_SOLVED"


class FlexibleResult(ContractModel):
    schema_version: Literal["1.0.0-rc1"] = "1.0.0-rc1"
    request: FlexibleOptionsRequest
    problem: CoreProblem
    receipt: FlexibleReceipt


def _id(r, kind, *parts):
    return stable_id(kind, r.source_ref.organisation_id, r.source_ref.schedule_id, r.target.schedule_id, *parts)


def _check(r):
    check_source(r.source_ref, r.source, r.target.organisation_id, r.target.schedule_id)
    errors = option_errors(r.source.demand, r.source.plan)
    if errors: raise HandoffError("INVALID_ACCEPTED_OPTION_PLAN", ";".join(e.code for e in errors))
    ts = {t.family_id: t for t in r.target.templates}
    if len(ts) != len(r.target.templates) or set(ts) != {f.id for f in r.source.demand.families}:
        raise HandoffError("CURRICULUM_MAPPING_INCOMPLETE", "One template per family")
    expected = {(s.id, o.key) for s in r.source.plan.offerings for o in ts[s.family_id].occurrences}
    bs = {(b.section_id, b.occurrence_key): b for b in r.target.bindings}
    if len(bs) != len(r.target.bindings) or set(bs) != expected:
        raise HandoffError("OCCURRENCE_MAP_INCOMPLETE", "Map every section occurrence exactly once")
    wins = {x.id for x in r.target.windows}; sections = {s.id: s for s in r.source.plan.offerings}
    syncs = defaultdict(list)
    for b in r.target.bindings:
        if len(set(b.candidate_start_ids)) != len(b.candidate_start_ids) or not set(b.candidate_start_ids) <= wins:
            raise HandoffError("INVALID_OCCURRENCE_DOMAIN", b.section_id)
        if b.sync_key: syncs[b.sync_key].append(b)
    for key, group in syncs.items():
        if len(group) < 2 or len({b.section_id for b in group}) != len(group):
            raise HandoffError("INVALID_ALIGNMENT_GROUP", key)
        if len({sections[b.section_id].block_id for b in group}) != 1:
            raise HandoffError("CROSS_BLOCK_ALIGNMENT", key)
    return ts, bs, syncs


def build_flexible_handoff(request: FlexibleOptionsRequest) -> FlexibleResult:
    r = FlexibleOptionsRequest.model_validate(request.model_dump(mode="json"))
    ts, bs, syncs = _check(r); src = r.source; cfg = r.target
    fs = {f.id: f for f in src.demand.families}; qs = {q.id: q for q in src.demand.requests}
    chosen = {a.request_id: a.offering_id for a in src.plan.allocations}
    members = defaultdict(set)
    for a in src.plan.allocations: members[a.offering_id].add(qs[a.request_id].participant_id)
    acts = []; offers = []; events = []; requests = []; rules = []; maps = []
    def mapping(sk, sid, tk, tid, comp=None):
        maps.append(EntityMapping(source_kind=sk, source_id=sid, source_component=comp, target_kind=tk, target_id=tid))
    for f in sorted(src.demand.families, key=lambda x:x.id):
        t = ts[f.id]; aid = _id(r,"activity",f.id)
        acts.append(Activity(id=aid,label=f.label,demand=Demand(basis="PER_ENROLLED",unit=t.unit,amount=t.required_units)))
        mapping("FAMILY",f.id,"ACTIVITY",aid)
    for s in sorted(src.plan.offerings,key=lambda x:x.id):
        oid = _id(r,"offering",s.id); aid = _id(r,"activity",s.family_id); ids=[]
        for o in ts[s.family_id].occurrences:
            eid=_id(r,"event",s.id,o.key); ids.append(eid); reqs=[]
            for q in ts[s.family_id].requirements:
                raw=q.model_dump(mode="json"); raw["id"]=_id(r,"requirement",s.id,o.key,q.id)
                if q.kind==ResourceKind.SPACE:
                    raw["minimum_capacity"]=max(q.minimum_capacity or 1,len(members[s.id]))
                reqs.append(ResourceRequirement.model_validate(raw))
            events.append(Event(id=eid,label=f"{fs[s.family_id].label} {s.id} {o.key}",activity_id=aid,
                offering_id=oid,required=False,duration=o.duration,requirements=reqs,
                placement=PlacementDomain(start_window_ids=bs[(s.id,o.key)].candidate_start_ids)))
            mapping("SECTION_OCCURRENCE",s.id,"EVENT",eid,o.key)
        offers.append(Offering(id=oid,activity_id=aid,event_ids=ids,capacity=fs[s.family_id].max_members))
        mapping("SECTION",s.id,"OFFERING",oid)
    for q in sorted(src.demand.requests,key=lambda x:x.id):
        qid=_id(r,"request",q.id)
        requests.append(ParticipationRequest(id=qid,participant_id=q.participant_id,activity_id=_id(r,"activity",q.family_id),
            eligible_offering_ids=[_id(r,"offering",chosen[q.id])],min_select=1,max_select=1,strength=RuleStrength.HARD))
        mapping("CHOICE",q.id,"PARTICIPATION_REQUEST",qid)
    for key, group in sorted(syncs.items()):
        rid=_id(r,"rule",key)
        rules.append(SameStart(id=rid,strength=RuleStrength.HARD,source=RuleSource.IMPORT,
                              event_ids=[_id(r,"event",b.section_id,b.occurrence_key) for b in group]))
        # Alignment belongs to target configuration, not an invented source-plan entity.
        mapping("TARGET_ALIGNMENT",key,"SYNCHRONISATION_RULE",rid)
    for pid in sorted(src.demand.participant_ids): mapping("PARTICIPANT",pid,"RESOURCE",pid)
    p=CoreProblem(problem_id=cfg.schedule_id,model_version=cfg.model_version,vertical_id="SCHOOLS",timezone=cfg.timezone,
        days=cfg.days,windows=cfg.windows,resources=cfg.resources,locations=cfg.locations,activities=acts,events=events,
        offerings=offers,participation_requests=requests,constraints=rules)
    errors=core_problem_errors(p)
    if errors: raise HandoffError("INVALID_PLACEMENT_INPUT",";".join(e.code for e in errors))
    return FlexibleResult(request=r,problem=p,receipt=FlexibleReceipt(source=r.source_ref,
        config_sha256=fingerprint(cfg),output_sha256=fingerprint(p),target_schedule_id=cfg.schedule_id,
        target_model_version=cfg.model_version,mappings=maps))


def flexible_handoff_errors(result: FlexibleResult) -> list[Finding]:
    """Reverse semantics check. Deliberately does not call build_flexible_handoff."""
    out=FlexibleResult.model_validate(result.model_dump(mode="json")); r=out.request; p=out.problem; rec=out.receipt
    errors=[]
    def bad(code,detail): errors.append(Finding(code=code,detail=detail))
    try: ts, bs, syncs=_check(r)
    except HandoffError as e: return [Finding(code=e.code,detail=e.detail)]
    errors += core_problem_errors(p)
    if errors:return errors
    if rec.source!=r.source_ref or rec.config_sha256!=fingerprint(r.target) or rec.output_sha256!=fingerprint(p):bad("HANDOFF_FINGERPRINT_MISMATCH","Source/config/output")
    if (rec.target_schedule_id,rec.target_model_version)!=(r.target.schedule_id,r.target.model_version):bad("HANDOFF_TARGET_CHANGED","Receipt")
    if (p.problem_id,p.model_version,p.timezone,p.days,p.windows,p.resources,p.locations)!=(r.target.schedule_id,r.target.model_version,r.target.timezone,r.target.days,r.target.windows,r.target.resources,r.target.locations):bad("TARGET_CONTEXT_CHANGED","Schedule/calendar/resources")
    if p.credentials or p.travel_arcs or p.locks or p.objectives or p.baseline_solution_id:bad("UNDECLARED_TARGET_RULES","Added target state")
    es={x.id:x for x in p.events}; os={x.id:x for x in p.offerings}; acts={x.id:x for x in p.activities}; rq={x.id:x for x in p.participation_requests}
    fs={f.id:f for f in r.source.demand.families}; sq={q.id:q for q in r.source.demand.requests}; chosen={a.request_id:a.offering_id for a in r.source.plan.allocations}
    membership=defaultdict(set)
    for a in r.source.plan.allocations:membership[a.offering_id].add(sq[a.request_id].participant_id)
    expected_es=set(); expected_os=set(); expected_maps=set()
    def mapping(sk,sid,tk,tid,comp=None):expected_maps.add((sk,sid,comp,tk,tid))
    for f in fs.values():
        aid=_id(r,"activity",f.id); a=acts.get(aid); t=ts[f.id]
        if a is None or a.label!=f.label or a.demand!=Demand(basis="PER_ENROLLED",unit=t.unit,amount=t.required_units):bad("CURRICULUM_CHANGED",f.id)
        mapping("FAMILY",f.id,"ACTIVITY",aid)
    if set(acts)!={_id(r,"activity",f) for f in fs}:bad("FAMILY_SET_CHANGED","Activities")
    for s in r.source.plan.offerings:
        oid=_id(r,"offering",s.id);expected_os.add(oid);offer=os.get(oid);t=ts[s.family_id];ids=[]
        for o in t.occurrences:
            eid=_id(r,"event",s.id,o.key);expected_es.add(eid);ids.append(eid);e=es.get(eid)
            if e is None:bad("LESSON_LOST",eid);continue
            if (e.activity_id,e.offering_id,e.required,e.fixed_participant_ids,e.duration,e.placement.start_window_ids)!=(_id(r,"activity",s.family_id),oid,False,[],o.duration,bs[(s.id,o.key)].candidate_start_ids):bad("OCCURRENCE_CHANGED",eid)
            reqs={q.id:q for q in e.requirements};expected_reqs=set()
            for q in t.requirements:
                qid=_id(r,"requirement",s.id,o.key,q.id);expected_reqs.add(qid);raw=q.model_dump(mode="json");raw["id"]=qid
                if q.kind==ResourceKind.SPACE:raw["minimum_capacity"]=max(q.minimum_capacity or 1,len(membership[s.id]))
                if reqs.get(qid)!=ResourceRequirement.model_validate(raw):bad("RESOURCE_DEMAND_CHANGED",qid)
            if set(reqs)!=expected_reqs:bad("REQUIREMENT_SET_CHANGED",eid)
            mapping("SECTION_OCCURRENCE",s.id,"EVENT",eid,o.key)
        if offer is None or offer.event_ids!=ids or offer.capacity!=fs[s.family_id].max_members or offer.activity_id!=_id(r,"activity",s.family_id):bad("SECTION_CHANGED",s.id)
        mapping("SECTION",s.id,"OFFERING",oid)
    if set(es)!=expected_es or set(os)!=expected_os:bad("SECTION_EVENT_SET_CHANGED","Added or lost events/sections")
    for q in r.source.demand.requests:
        qid=_id(r,"request",q.id);actual=rq.get(qid)
        if actual is None or (actual.participant_id,actual.activity_id,actual.eligible_offering_ids,actual.min_select,actual.max_select,actual.strength)!=(q.participant_id,_id(r,"activity",q.family_id),[_id(r,"offering",chosen[q.id])],1,1,RuleStrength.HARD):bad("ACCEPTED_CHOICE_CHANGED",q.id)
        mapping("CHOICE",q.id,"PARTICIPATION_REQUEST",qid)
    if set(rq)!={_id(r,"request",q) for q in sq}:bad("REQUEST_SET_CHANGED","Requests")
    expected_rules={_id(r,"rule",key):{_id(r,"event",b.section_id,b.occurrence_key) for b in group} for key,group in syncs.items()}
    if len(p.constraints)!=len(expected_rules):bad("ALIGNMENT_SET_CHANGED","Rules")
    for rule in p.constraints:
        if not isinstance(rule,SameStart) or not rule.enabled or rule.strength!=RuleStrength.HARD or set(rule.event_ids)!=expected_rules.get(rule.id):bad("ALIGNMENT_CHANGED",rule.id)
    for key in syncs:mapping("TARGET_ALIGNMENT",key,"SYNCHRONISATION_RULE",_id(r,"rule",key))
    for pid in r.source.demand.participant_ids:mapping("PARTICIPANT",pid,"RESOURCE",pid)
    actual_maps={(m.source_kind,m.source_id,m.source_component,m.target_kind,m.target_id) for m in rec.mappings}
    if actual_maps!=expected_maps or len(rec.mappings)!=len(expected_maps):bad("LINEAGE_MANIFEST_CHANGED","Mappings")
    return errors
