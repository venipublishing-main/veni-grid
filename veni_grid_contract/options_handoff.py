"""Accepted options -> lesson placement input. A deterministic adapter, not a solver.

Supported profile: all source choices fulfilled; all sections of a block have the
same explicitly supplied occurrence pattern. More flexible blocks must be modelled
as a different supported profile, never silently flattened into labels.
"""
from __future__ import annotations
from collections import defaultdict
from typing import Literal
from pydantic import Field, model_validator

from .models import (ID, Day, TimeWindow, Resource, ResourceKind, Duration,
    ResourceRequirement, Activity, Demand, Offering, ParticipationRequest, Event,
    PlacementDomain, RuleStrength, RuleSource)
from .option_design import OptionDesignProblem, OptionDesignWitness, option_errors
from .primitives import ContractModel, Positive, Finding
from .handoff_common import (SnapshotRef, HandoffError, HandoffReceipt, EntityMapping,
    check_source, fingerprint, stable_id, receipt, receipt_errors)
from .placement_v04 import PlacementProblem, SameStart, placement_problem_errors


class AcceptedOptions(ContractModel):
    schema_version: Literal["0.4.0-draft"] = "0.4.0-draft"
    demand: OptionDesignProblem
    plan: OptionDesignWitness


class LessonOccurrence(ContractModel):
    key: ID
    duration: Duration


class LessonTemplate(ContractModel):
    family_id: ID
    unit: Literal["WINDOWS", "MINUTES"]
    required_units: Positive
    occurrences: list[LessonOccurrence] = Field(min_length=1)
    requirements: list[ResourceRequirement] = Field(min_length=1)

    @model_validator(mode="after")
    def coherent_demand(self):
        if len({o.key for o in self.occurrences}) != len(self.occurrences):
            raise ValueError("Duplicate occurrence key")
        if any(o.duration.unit != self.unit for o in self.occurrences):
            raise ValueError("Mixed demand units unsupported")
        if sum(o.duration.count for o in self.occurrences) != self.required_units:
            raise ValueError("Occurrence pattern does not match required curriculum demand")
        if len({r.id for r in self.requirements}) != len(self.requirements):
            raise ValueError("Duplicate requirement key")
        if sum(r.quantity for r in self.requirements if r.kind == ResourceKind.SPACE) != 1:
            raise ValueError("This bridge profile requires exactly one space per lesson")
        return self


class BlockBinding(ContractModel):
    block_id: ID
    occurrence_key: ID
    candidate_start_ids: list[ID] = Field(min_length=1)


class LessonTargetConfig(ContractModel):
    organisation_id: ID
    schedule_id: ID
    model_version: Positive
    timezone: str = "Africa/Johannesburg"
    days: list[Day] = Field(min_length=1)
    windows: list[TimeWindow] = Field(min_length=1)
    resources: list[Resource] = Field(min_length=1)
    templates: list[LessonTemplate] = Field(min_length=1)
    bindings: list[BlockBinding] = Field(min_length=1)


class OptionsHandoff(ContractModel):
    schema_version: Literal["0.4.0-draft"] = "0.4.0-draft"
    source_ref: SnapshotRef
    source: AcceptedOptions
    target: LessonTargetConfig


class LessonHandoffResult(ContractModel):
    schema_version: Literal["0.4.0-draft"] = "0.4.0-draft"
    request: OptionsHandoff
    problem: PlacementProblem
    receipt: HandoffReceipt


def _check(request: OptionsHandoff) -> None:
    src, cfg = request.source, request.target
    check_source(request.source_ref, src, cfg.organisation_id, cfg.schedule_id)
    problems = option_errors(src.demand, src.plan)
    if problems:
        raise HandoffError("INVALID_ACCEPTED_OPTION_PLAN", "; ".join(x.code for x in problems))
    fam = {f.id for f in src.demand.families}
    templates = {x.family_id: x for x in cfg.templates}
    if len(templates) != len(cfg.templates) or set(templates) != fam:
        raise HandoffError("CURRICULUM_MAPPING_INCOMPLETE", "Exactly one template per source family required")
    catalog = {r.id: r for r in cfg.resources}
    if len(catalog) != len(cfg.resources):
        raise HandoffError("DUPLICATE_RESOURCE", "Target resource catalogue")
    for pid in src.demand.participant_ids:
        if pid not in catalog or catalog[pid].kind != ResourceKind.PERSON:
            raise HandoffError("LEARNER_IDENTITY_UNRESOLVED", pid)
    bindings = {(b.block_id, b.occurrence_key): b for b in cfg.bindings}
    if len(bindings) != len(cfg.bindings):
        raise HandoffError("DUPLICATE_BLOCK_BINDING", "Repeated block/occurrence")
    expected = set(); patterns = {}
    for offer in src.plan.offerings:
        template = templates[offer.family_id]
        pattern = sorted((o.key, fingerprint(o.duration)) for o in template.occurrences)
        if offer.block_id in patterns and patterns[offer.block_id] != pattern:
            raise HandoffError("UNSUPPORTED_BLOCK_PATTERN", "Synchronous-block occurrence patterns must agree")
        patterns[offer.block_id] = pattern
        expected |= {(offer.block_id, o.key) for o in template.occurrences}
    if set(bindings) != expected:
        raise HandoffError("BLOCK_BINDING_INCOMPLETE", "Missing or extraneous block occurrences")
    wins = {w.id for w in cfg.windows}
    for bind in cfg.bindings:
        if len(set(bind.candidate_start_ids)) != len(bind.candidate_start_ids) or not set(bind.candidate_start_ids) <= wins:
            raise HandoffError("INVALID_BLOCK_DOMAIN", bind.block_id)


def _id(req: OptionsHandoff, kind: str, *parts: str) -> str:
    return stable_id(kind, req.source_ref.organisation_id, req.source_ref.schedule_id,
                     req.target.schedule_id, *parts)


def build_lesson_handoff(request: OptionsHandoff) -> LessonHandoffResult:
    # Reparse to catch caller-side mutation/model_copy shortcuts; never mutate the input.
    request = OptionsHandoff.model_validate(request.model_dump(mode="json"))
    _check(request)
    src, cfg = request.source, request.target
    families = {f.id: f for f in src.demand.families}
    templates = {t.family_id: t for t in cfg.templates}
    allocations = {a.request_id: a.offering_id for a in src.plan.allocations}
    requests = {r.id: r for r in src.demand.requests}
    members = defaultdict(set)
    for a in src.plan.allocations:
        members[a.offering_id].add(requests[a.request_id].participant_id)
    bindings = {(b.block_id, b.occurrence_key): b for b in cfg.bindings}
    mappings: list[EntityMapping] = []
    def mapped(kind, sid, target_kind, tid, component=None):
        mappings.append(EntityMapping(source_kind=kind, source_id=sid, source_component=component,
                                      target_kind=target_kind, target_id=tid))
    acts, offers, events, choices, rules = [], [], [], [], []
    sync_groups = defaultdict(list)
    for fid, family in sorted(families.items()):
        t = templates[fid]; aid = _id(request, "activity", fid)
        acts.append(Activity(id=aid, label=family.label,
                             demand=Demand(basis="PER_ENROLLED", unit=t.unit, amount=t.required_units)))
        mapped("FAMILY", fid, "ACTIVITY", aid)
    for offer in sorted(src.plan.offerings, key=lambda x: x.id):
        oid = _id(request, "offering", offer.id); aid = _id(request, "activity", offer.family_id)
        template = templates[offer.family_id]; event_ids = []
        for occurrence in template.occurrences:
            eid = _id(request, "event", offer.id, occurrence.key); event_ids.append(eid)
            requirements = []
            for q in template.requirements:
                values = q.model_dump(mode="json")
                values["id"] = _id(request, "requirement", offer.id, occurrence.key, q.id)
                if q.kind == ResourceKind.SPACE:
                    values["minimum_capacity"] = max(q.minimum_capacity or 1, len(members[offer.id]))
                requirements.append(ResourceRequirement.model_validate(values))
            events.append(Event(id=eid, label=f"{families[offer.family_id].label} {offer.id} {occurrence.key}",
                activity_id=aid, offering_id=oid, required=False, duration=occurrence.duration,
                placement=PlacementDomain(start_window_ids=bindings[(offer.block_id, occurrence.key)].candidate_start_ids),
                requirements=requirements))
            sync_groups[(offer.block_id, occurrence.key)].append(eid)
            mapped("SECTION_OCCURRENCE", offer.id, "EVENT", eid, occurrence.key)
        offers.append(Offering(id=oid, activity_id=aid, event_ids=event_ids,
                               capacity=families[offer.family_id].max_members))
        mapped("SECTION", offer.id, "OFFERING", oid)
    for r in sorted(src.demand.requests, key=lambda x: x.id):
        rid = _id(request, "request", r.id)
        choices.append(ParticipationRequest(id=rid, participant_id=r.participant_id,
            activity_id=_id(request, "activity", r.family_id),
            eligible_offering_ids=[_id(request, "offering", allocations[r.id])],
            min_select=1, max_select=1, strength=RuleStrength.HARD))
        mapped("CHOICE", r.id, "PARTICIPATION_REQUEST", rid)
    for (bid, key), ids in sorted(sync_groups.items()):
        if len(ids) > 1:
            rule_id = _id(request, "rule", bid, key)
            rules.append(SameStart(id=rule_id, strength=RuleStrength.HARD,
                                  source=RuleSource.IMPORT, event_ids=ids))
            mapped("BLOCK_OCCURRENCE", bid, "SYNCHRONISATION_RULE", rule_id, key)
    for pid in sorted(src.demand.participant_ids):
        mapped("PARTICIPANT", pid, "RESOURCE", pid)
    p = PlacementProblem(problem_id=cfg.schedule_id, model_version=cfg.model_version,
        vertical_id="SCHOOLS", timezone=cfg.timezone, days=cfg.days, windows=cfg.windows,
        resources=cfg.resources, activities=acts, offerings=offers, events=events,
        participation_requests=choices, constraints=rules)
    errors = placement_problem_errors(p)
    if errors:
        raise HandoffError("INVALID_PLACEMENT_INPUT", "; ".join(x.code for x in errors))
    info = receipt("OPTIONS_TO_LESSONS", request.source_ref, cfg, p, cfg.schedule_id, mappings,
        ["Accepted choices are pinned; changing them needs an explicit upstream review.",
         "This synchronous-block profile requires equal occurrence patterns within each block.",
         "No timetable feasibility, teacher/room allocation or optimisation has been computed."])
    result = LessonHandoffResult(request=request, problem=p, receipt=info)
    return LessonHandoffResult.model_validate_json(result.model_dump_json())


def lesson_handoff_errors(result: LessonHandoffResult) -> list[Finding]:
    """Independent reverse checks: inspect target meaning; do not call the adapter."""
    result = LessonHandoffResult.model_validate(result.model_dump(mode="json"))
    req, p, rec = result.request, result.problem, result.receipt
    errors: list[Finding] = []
    def bad(code, detail): errors.append(Finding(code=code, detail=detail))
    try: _check(req)
    except HandoffError as exc:
        bad(exc.code, exc.detail); return errors
    for e in placement_problem_errors(p): bad(e.code, e.message)
    if errors: return errors
    errors.extend(receipt_errors(rec,"OPTIONS_TO_LESSONS",req.source_ref,req.target,p,req.target.schedule_id))
    if rec.source != req.source_ref or rec.config_sha256 != fingerprint(req.target):
        bad("RECEIPT_LINEAGE_MISMATCH", "Source/config")
    if rec.output_sha256 != fingerprint(p): bad("OUTPUT_FINGERPRINT_MISMATCH", "Lesson input")
    if rec.target_schedule_id != req.target.schedule_id or rec.target_model_version != p.model_version:
        bad("RECEIPT_TARGET_MISMATCH", "Target")
    if (p.problem_id, p.model_version, p.timezone) != (req.target.schedule_id, req.target.model_version, req.target.timezone):
        bad("TARGET_IDENTITY_CHANGED", "Lesson target")
    if (p.days, p.windows, p.resources) != (req.target.days, req.target.windows, req.target.resources):
        bad("TARGET_CONTEXT_CHANGED", "Calendar/resources")
    src = req.source; templates = {t.family_id:t for t in req.target.templates}
    choices = {r.id:r for r in src.demand.requests}; selected = {a.request_id:a.offering_id for a in src.plan.allocations}
    catalog = {o.id:o for o in p.offerings}; actual_requests = {r.id:r for r in p.participation_requests}
    acts = {a.id:a for a in p.activities}; evs = {e.id:e for e in p.events}
    member_counts = defaultdict(set)
    for a in src.plan.allocations: member_counts[a.offering_id].add(choices[a.request_id].participant_id)
    expected_offer_ids = {_id(req,"offering",o.id) for o in src.plan.offerings}
    if set(catalog) != expected_offer_ids: bad("SECTION_SET_CHANGED", "Offerings omitted or added")
    if set(acts) != {_id(req,"activity",f.id) for f in src.demand.families}: bad("FAMILY_SET_CHANGED", "Activities")
    if set(actual_requests) != {_id(req,"request",r.id) for r in src.demand.requests}: bad("REQUEST_SET_CHANGED", "Choices")
    bindings = {(b.block_id,b.occurrence_key):b.candidate_start_ids for b in req.target.bindings}
    expected_events = set(); sync = defaultdict(set)
    for f in src.demand.families:
        a = acts.get(_id(req,"activity",f.id)); t = templates[f.id]
        if a is None or a.label != f.label or (a.demand.basis,a.demand.unit,a.demand.amount)!=("PER_ENROLLED",t.unit,t.required_units):
            bad("CURRICULUM_DEMAND_CHANGED", f.id)
    for o in src.plan.offerings:
        oid = _id(req,"offering",o.id); actual = catalog.get(oid); t = templates[o.family_id]
        family = next(f for f in src.demand.families if f.id==o.family_id)
        event_ids = {_id(req,"event",o.id,x.key) for x in t.occurrences}; expected_events |= event_ids
        if actual is None or set(actual.event_ids)!=event_ids or actual.capacity!=family.max_members:
            bad("SECTION_DEMAND_CHANGED", o.id)
        for occ in t.occurrences:
            eid = _id(req,"event",o.id,occ.key); e = evs.get(eid); sync[(o.block_id,occ.key)].add(eid)
            if e is None: bad("LESSON_LOST",eid); continue
            if (e.duration,e.placement.start_window_ids,e.offering_id,e.activity_id,e.required,e.fixed_participant_ids)!=(
                occ.duration,bindings[(o.block_id,occ.key)],oid,_id(req,"activity",o.family_id),False,[]):
                bad("LESSON_MEANING_CHANGED",eid)
            expected_requirements=[]
            for q in t.requirements:
                raw=q.model_dump(mode="json");raw["id"]=_id(req,"requirement",o.id,occ.key,q.id)
                if q.kind==ResourceKind.SPACE:
                    raw["minimum_capacity"]=max(q.minimum_capacity or 1,len(member_counts[o.id]))
                expected_requirements.append(ResourceRequirement.model_validate(raw))
            if e.requirements!=expected_requirements: bad("RESOURCE_DEMAND_CHANGED",eid)
    if set(evs)!=expected_events: bad("LESSON_SET_CHANGED","Unexpected event set")
    for r in src.demand.requests:
        a=actual_requests.get(_id(req,"request",r.id))
        if a is None or (a.participant_id,a.activity_id,a.eligible_offering_ids,a.min_select,a.max_select,a.strength)!=(
            r.participant_id,_id(req,"activity",r.family_id),[_id(req,"offering",selected[r.id])],1,1,RuleStrength.HARD):
            bad("ACCEPTED_CHOICE_CHANGED",r.id)
    expected_sync={frozenset(ids) for ids in sync.values() if len(ids)>1}
    actual_sync={frozenset(c.event_ids) for c in p.constraints if isinstance(c,SameStart) and c.enabled and c.strength==RuleStrength.HARD}
    if actual_sync!=expected_sync or len(p.constraints)!=len(expected_sync): bad("BLOCK_RULE_LOST","Synchronisation")
    if p.locks or p.objectives or p.baseline_solution_id is not None:
        bad("UNDECLARED_TARGET_STATE","No extra locks/objectives/baseline accepted by this handoff profile")
    # Required section/choice traceability is independently checked, including duplicates.
    mapkeys=[(m.source_kind,m.source_id,m.target_kind,m.target_id) for m in rec.mappings]
    if len(mapkeys)!=len(set(mapkeys)): bad("DUPLICATE_LINEAGE_MAPPING","Receipt mappings")
    for o in src.plan.offerings:
        if ("SECTION",o.id,"OFFERING",_id(req,"offering",o.id)) not in mapkeys: bad("SECTION_LINEAGE_LOST",o.id)
    for r in src.demand.requests:
        if ("CHOICE",r.id,"PARTICIPATION_REQUEST",_id(req,"request",r.id)) not in mapkeys: bad("REQUEST_LINEAGE_LOST",r.id)
    expected_maps=set()
    for f in src.demand.families:
        expected_maps.add(("FAMILY",f.id,None,"ACTIVITY",_id(req,"activity",f.id)))
    for o in src.plan.offerings:
        expected_maps.add(("SECTION",o.id,None,"OFFERING",_id(req,"offering",o.id)))
        for occ in templates[o.family_id].occurrences:
            expected_maps.add(("SECTION_OCCURRENCE",o.id,occ.key,"EVENT",_id(req,"event",o.id,occ.key)))
    for r in src.demand.requests:
        expected_maps.add(("CHOICE",r.id,None,"PARTICIPATION_REQUEST",_id(req,"request",r.id)))
    for pid in src.demand.participant_ids:
        expected_maps.add(("PARTICIPANT",pid,None,"RESOURCE",pid))
    for (bid,key),ids in sync.items():
        if len(ids)>1:
            expected_maps.add(("BLOCK_OCCURRENCE",bid,key,"SYNCHRONISATION_RULE",_id(req,"rule",bid,key)))
    actual_maps={(m.source_kind,m.source_id,m.source_component,m.target_kind,m.target_id) for m in rec.mappings}
    if actual_maps!=expected_maps or len(rec.mappings)!=len(expected_maps):
        bad("LINEAGE_MANIFEST_MISMATCH","Missing, extra or altered source-to-target mapping")
    return errors
