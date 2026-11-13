"""C2.0: O1 accepted section plan -> verified teacher and room lesson placement.

This is a *standalone*, fixed-option-plan feasibility profile. It cannot choose
new O1 blocks or alter accepted learners/sections. A preflight matching proof
catches concurrent teacher/room shortfalls; the real C1 CP-SAT solver then
places every lesson, with the independent C1 and handoff validators as gates.

C2 is not a full closed-loop O1 re-sectioning optimizer or a publisher.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Literal
from pydantic import Field, ValidationError

from veni_grid_contract.models import (
    ID, Day, TimeWindow, ResourceKind, ResourceRequirement, RuleStrength,
    RuleSource,
)
from veni_grid_contract.core_v1 import (
    CoreProblem, CoreWitness, LocatedResource, Location, Credential,
    QualificationRule, ContinuityRule, AllocationRef, CoreRule, core_problem_errors,
)
from veni_grid_contract.option_design import option_errors
from veni_grid_contract.options_handoff import AcceptedOptions, LessonOccurrence, LessonTemplate
from veni_grid_contract.flexible_options import (
    FlexibleTarget, FlexibleOptionsRequest, OccurrenceBinding,
    build_flexible_handoff, flexible_handoff_errors,
)
from veni_grid_contract.handoff_common import (
    SnapshotRef, HandoffError, check_source, fingerprint, stable_id,
)
from veni_grid_contract.primitives import ContractModel, Positive
from veni_grid_solver import solve as solve_placement
from veni_grid_contract.conformance import review_core


class C2FamilyTeaching(ContractModel):
    family_id: ID
    competency_code: ID
    teacher_ids: list[ID] = Field(min_length=1)
    room_ids: list[ID] = Field(min_length=1)
    required_room_tags: list[str] = Field(default_factory=list)
    occurrences: list[LessonOccurrence] = Field(min_length=1)
    same_teacher_across_occurrences: bool = True
    same_room_across_occurrences: bool = False


class C2BlockWindow(ContractModel):
    block_id: ID
    occurrence_key: ID
    # Explicit calendar/day placement: the opaque occurrence key is not
    # interpreted as a date or cycle-day name.
    allowed_day_ids: list[ID] = Field(min_length=1)
    candidate_start_ids: list[ID] = Field(min_length=1)


class C2Target(ContractModel):
    organisation_id: ID
    schedule_id: ID
    model_version: Positive
    timezone: str = "Africa/Johannesburg"
    days: list[Day] = Field(min_length=1)
    windows: list[TimeWindow] = Field(min_length=1)
    resources: list[LocatedResource] = Field(min_length=1)
    locations: list[Location] = Field(default_factory=list)
    credentials: list[Credential] = Field(default_factory=list)
    family_teaching: list[C2FamilyTeaching] = Field(min_length=1)
    block_windows: list[C2BlockWindow] = Field(min_length=1)
    # User/organisation-supplied hard conditions; never import other schedules silently.
    constraints: list[CoreRule] = Field(default_factory=list)
    relationship: Literal["STANDALONE"] = "STANDALONE"


class C2Input(ContractModel):
    version: Literal["0.1.0"] = "0.1.0"
    source_ref: SnapshotRef
    source: AcceptedOptions
    target: C2Target


class C2Result(ContractModel):
    version: Literal["0.1.0"] = "0.1.0"
    status: Literal["FEASIBLE", "INFEASIBLE", "UNKNOWN", "INVALID_INPUT", "UNSUPPORTED", "ERROR"]
    stage: Literal["SOURCE", "STATIC_RESOURCE_PREFLIGHT", "PLACEMENT", "DONE"] = "SOURCE"
    findings: list[str] = Field(default_factory=list)
    # Both preflight proofs and CP-SAT proofs apply ONLY to this fixed O1 plan
    # and the supplied local scheduling context; not arbitrary future O1 plans.
    proof_scope: Literal["FIXED_O1_C2", "NONE"] = "NONE"
    source_fingerprint: str | None = None
    target_fingerprint: str | None = None
    output_fingerprint: str | None = None
    source_unchanged: bool = False
    placement_problem: CoreProblem | None = None
    candidate: CoreWitness | None = None
    event_count: int = 0
    teacher_assignments: dict[str, str] = Field(default_factory=dict)
    room_assignments: dict[str, str] = Field(default_factory=dict)
    independent_hard_validation: Literal["PASSED", "FAILED", "NOT_RUN"] = "NOT_RUN"
    solver_status: str = "NOT_RUN"
    quality_optimisation: Literal["NOT_PERFORMED"] = "NOT_PERFORMED"
    organisation_wide_clashes: Literal["NOT_ASSESSED"] = "NOT_ASSESSED"
    publication: Literal["NOT_GRANTED"] = "NOT_GRANTED"


class C2Failure(ValueError):
    def __init__(self, code: str, message: str, *, infeasible: bool = False, unsupported: bool = False):
        self.code, self.message = code, message
        self.infeasible, self.unsupported = infeasible, unsupported
        super().__init__(f"{code}: {message}")


def _maximum_matching(edges: dict[str, set[str]]) -> int:
    """Independent augmenting-path proof of max simultaneous distinct resources.

    Unlike a crude total-capacity count, catches Hall-set shortfalls such as
    three Science sections competing for two of four otherwise free rooms.
    """
    owner: dict[str, str] = {}
    def augment(section: str, visited: set[str]) -> bool:
        for resource in sorted(edges[section]):
            if resource in visited:
                continue
            visited.add(resource)
            if resource not in owner or augment(owner[resource], visited):
                owner[resource] = section
                return True
        return False
    matched = 0
    for section in sorted(edges):
        if augment(section, set()):
            matched += 1
    return matched


def _check_and_prepare(request: C2Input):
    src, cfg = request.source, request.target
    check_source(request.source_ref, src, cfg.organisation_id, cfg.schedule_id)
    errors = option_errors(src.demand, src.plan)
    if errors:
        raise C2Failure("INVALID_O1_WITNESS", "; ".join(f"{e.code}:{e.detail}" for e in errors[:8]))
    specs = {f.family_id: f for f in cfg.family_teaching}
    families = {f.id for f in src.demand.families}
    if len(specs) != len(cfg.family_teaching) or set(specs) != families:
        raise C2Failure("MISSING_SUBJECT_TEACHING", "Exactly one curriculum/teacher/room specification per requested subject")
    rs = {r.id: r for r in cfg.resources}
    if len(rs) != len(cfg.resources):
        raise C2Failure("DUPLICATE_RESOURCE", "Resource catalogue must have unique IDs")
    if len(cfg.constraints) != len({rule.id for rule in cfg.constraints}):
        raise C2Failure("DUPLICATE_EXTRA_RULE", "Provided hard-rule IDs must be unique")
    if any(rule.strength != RuleStrength.HARD for rule in cfg.constraints):
        raise C2Failure("UNSCORED_SOFT_RULE", "C2 feasibility does not silently ignore soft preferences", unsupported=True)
    for person in src.demand.participant_ids:
        if person not in rs or rs[person].kind != ResourceKind.PERSON or "LEARNER" not in rs[person].tags:
            raise C2Failure("LEARNER_RESOURCE_UNRESOLVED", person)
    creds = {(c.resource_id, c.competency) for c in cfg.credentials}
    if len({c.id for c in cfg.credentials}) != len(cfg.credentials):
        raise C2Failure("DUPLICATE_CREDENTIAL", "Duplicate credential IDs")
    for credential in cfg.credentials:
        if credential.resource_id not in rs or rs[credential.resource_id].kind != ResourceKind.PERSON:
            raise C2Failure("INVALID_CREDENTIAL_SUBJECT", credential.id)
        # Dated qualifications must be assessed on an actual dated horizon.
        if credential.valid_during is not None and any(day.date is None for day in cfg.days):
            raise C2Failure("DATED_QUALIFICATION_ON_CYCLE", credential.id, unsupported=True)
    members = defaultdict(set)
    requests = {r.id: r for r in src.demand.requests}
    for a in src.plan.allocations:
        members[a.offering_id].add(requests[a.request_id].participant_id)
    # Filter ONLY by explicitly authorised supplied competency assertions and
    # room tags/capacity. CP-SAT still rechecks qualifications and availability.
    eligible_teacher: dict[str, list[str]] = {}
    eligible_room: dict[tuple[str, int], list[str]] = {}
    for fid, spec in specs.items():
        if not spec.occurrences or len({o.key for o in spec.occurrences}) != len(spec.occurrences):
            raise C2Failure("INVALID_CURRICULUM", f"Duplicate/no occurrence keys in {fid}")
        for tid in spec.teacher_ids:
            if tid not in rs or rs[tid].kind != ResourceKind.PERSON or "TEACHER" not in rs[tid].tags:
                raise C2Failure("UNKNOWN_TEACHER", f"{fid}: {tid}")
        for rid in spec.room_ids:
            if rid not in rs or rs[rid].kind != ResourceKind.SPACE:
                raise C2Failure("UNKNOWN_ROOM", f"{fid}: {rid}")
            if rs[rid].sharing_mode != "EXCLUSIVE":
                raise C2Failure("SHARED_SPACE_UNSUPPORTED",
                    f"{fid}: {rid}; C2 initial matching profile requires an exclusive room",
                    unsupported=True)
        eligible_teacher[fid] = sorted(tid for tid in set(spec.teacher_ids) if (tid, spec.competency_code) in creds)
    block_occurrence_sections = defaultdict(list)
    for o in src.plan.offerings:
        spec = specs[o.family_id]
        for occurrence in spec.occurrences:
            block_occurrence_sections[o.block_id, occurrence.key].append(o)
        size = len(members[o.id])
        eligible_room[o.id, size] = sorted(rid for rid in set(spec.room_ids)
            if rs[rid].capacity is not None and rs[rid].capacity >= size
            and set(spec.required_room_tags) <= set(rs[rid].tags))
    bindings = {(b.block_id, b.occurrence_key): b for b in cfg.block_windows}
    if len(bindings) != len(cfg.block_windows) or set(bindings) != set(block_occurrence_sections):
        raise C2Failure("BLOCK_OCCURRENCE_DOMAIN_MISMATCH", "Each block's active lesson occurrence needs exactly one start domain")
    window_by_id = {w.id:w for w in cfg.windows}
    day_ids={d.id for d in cfg.days}
    for b in cfg.block_windows:
        if (len(b.candidate_start_ids) != len(set(b.candidate_start_ids))
            or not set(b.candidate_start_ids) <= set(window_by_id)
            or len(b.allowed_day_ids) != len(set(b.allowed_day_ids))
            or not set(b.allowed_day_ids) <= day_ids):
            raise C2Failure("INVALID_BLOCK_TIME_DOMAIN", f"{b.block_id}/{b.occurrence_key}")
        if any(window_by_id[wid].day_id not in b.allowed_day_ids for wid in b.candidate_start_ids):
            raise C2Failure("BLOCK_WINDOW_DAY_MISMATCH", f"{b.block_id}/{b.occurrence_key}")
    for (bid, key), sections in sorted(block_occurrence_sections.items()):
        teachers = {o.id: set(eligible_teacher[o.family_id]) for o in sections}
        rooms = {o.id: set(eligible_room[o.id, len(members[o.id])]) for o in sections}
        count = len(sections)
        tc, rc = _maximum_matching(teachers), _maximum_matching(rooms)
        if tc < count:
            raise C2Failure("BLOCK_TEACHER_SHORTAGE",
                f"{bid}/{key}: only {tc} of {count} simultaneous sections can be matched to distinct qualified teachers",
                infeasible=True)
        if rc < count:
            raise C2Failure("BLOCK_CLASSROOM_SHORTAGE",
                f"{bid}/{key}: only {rc} of {count} simultaneous sections can be assigned distinct suitable rooms with enough seats",
                infeasible=True)
    return specs, eligible_teacher, eligible_room, members, block_occurrence_sections


def build_c2_problem(value: C2Input) -> tuple[CoreProblem, dict[str, dict[str, str]]]:
    """Create a hard-checkable C1 model WITHOUT reassigning any O1 learner.

    The existing independently reviewed `build_flexible_handoff` creates the
    underlying learner/section/occurrence mapping, so C2 does not duplicate it.
    """
    request = C2Input.model_validate(value.model_dump(mode="json") if isinstance(value, C2Input) else value)
    specs, teachers, rooms, members, sync_groups = _check_and_prepare(request)
    cfg, src = request.target, request.source
    templates = []
    for spec in cfg.family_teaching:
        # Use the union of suitable rooms across source sections. The existing
        # handoff then applies each individual section's exact size as its own
        # minimum capacity, so a 20-seat room can serve a 15-person section
        # without incorrectly serving a 25-person section.
        room_ids = sorted({rid for o in src.plan.offerings if o.family_id == spec.family_id
                           for rid in rooms[o.id, len(members[o.id])]})
        if not room_ids:
            raise C2Failure("NO_COMPATIBLE_CLASSROOM", spec.family_id, infeasible=True)
        required = sum(occurrence.duration.count for occurrence in spec.occurrences)
        unit = spec.occurrences[0].duration.unit
        if any(occurrence.duration.unit != unit for occurrence in spec.occurrences):
            raise C2Failure("MIXED_CURRICULUM_UNITS", spec.family_id, unsupported=True)
        template = LessonTemplate(family_id=spec.family_id, unit=unit, required_units=required,
            occurrences=spec.occurrences, requirements=[
                ResourceRequirement(id="req:TEACHER", role="TEACHER", kind=ResourceKind.PERSON,
                                    quantity=1, eligible_resource_ids=teachers[spec.family_id]),
                ResourceRequirement(id="req:ROOM", role="ROOM", kind=ResourceKind.SPACE,
                                    quantity=1, eligible_resource_ids=room_ids,
                                    minimum_capacity=1)
            ])
        templates.append(template)
    # IMPORTANT: ID mapping must preserve qualified teacher/room choice at
    # section level. Eligibility common across a family may still contain a
    # smaller room not valid for larger section; per-event minimum capacity
    # catches it with no invented resource flexibility.
    bindings = []
    for section in src.plan.offerings:
        for occurrence in specs[section.family_id].occurrences:
            block, key = section.block_id, occurrence.key
            pool = next(b.candidate_start_ids for b in cfg.block_windows
                        if b.block_id == block and b.occurrence_key == key)
            size = len(sync_groups[block, key])
            bindings.append(OccurrenceBinding(section_id=section.id, occurrence_key=key,
                candidate_start_ids=pool,
                sync_key=stable_id("sync", block, key) if size > 1 else None))
    target = FlexibleTarget(
        organisation_id=cfg.organisation_id, schedule_id=cfg.schedule_id,
        model_version=cfg.model_version, timezone=cfg.timezone, days=cfg.days,
        windows=cfg.windows, resources=cfg.resources, locations=cfg.locations,
        templates=templates, bindings=bindings)
    source = FlexibleOptionsRequest(source_ref=request.source_ref, source=src, target=target)
    bridge = build_flexible_handoff(source)
    check = flexible_handoff_errors(bridge)
    if check:
        raise C2Failure("FLEX_HANDOFF_REVERSE_CHECK_FAILED", "; ".join(x.code for x in check[:5]))
    p = bridge.problem.model_copy(deep=True)
    p.credentials = cfg.credentials
    # Eligibility already restricts to qualified candidates; the credentials
    # are also enforced as C1 QualificationRule in the actual CP-SAT solve.
    rules = list(p.constraints)
    for s in src.plan.offerings:
        spec = specs[s.family_id]
        # The existing handoff receipt supplies audited section/occurrence IDs.
        mappings = [m for m in bridge.receipt.mappings if m.source_kind == "SECTION_OCCURRENCE" and m.source_id == s.id]
        target_events = sorted((m.source_component, m.target_id) for m in mappings)
        refs_teacher = []
        refs_room = []
        for key, eid in target_events:
            e = next(e for e in p.events if e.id == eid)
            rt = next(q for q in e.requirements if q.role == "TEACHER")
            rr = next(q for q in e.requirements if q.role == "ROOM")
            refs_teacher.append(AllocationRef(event_id=eid, requirement_id=rt.id))
            refs_room.append(AllocationRef(event_id=eid, requirement_id=rr.id))
        rules.append(QualificationRule(id=stable_id("rulequal", cfg.schedule_id, s.id),
            source=RuleSource.SYSTEM, strength=RuleStrength.HARD,
            allocations=refs_teacher, all_of=[spec.competency_code]))
        if spec.same_teacher_across_occurrences and len(refs_teacher)>1:
            rules.append(ContinuityRule(id=stable_id("ruleteacher",cfg.schedule_id,s.id),
                source=RuleSource.SYSTEM,strength=RuleStrength.HARD,allocations=refs_teacher))
        if spec.same_room_across_occurrences and len(refs_room)>1:
            rules.append(ContinuityRule(id=stable_id("ruleroom",cfg.schedule_id,s.id),
                source=RuleSource.SYSTEM,strength=RuleStrength.HARD,allocations=refs_room))
    rules.extend(cfg.constraints)
    p.constraints = rules
    errors = core_problem_errors(p)
    if errors:
        raise C2Failure("INVALID_C2_PLACEMENT_MODEL", "; ".join(f"{x.code}: {x.detail}" for x in errors[:10]))
    lineage = {"source":request.source_ref.content_sha256,"target":fingerprint(cfg),"problem":fingerprint(p)}
    return p, lineage


def solve_c2(value: C2Input, *, time_limit_seconds: float = 30) -> C2Result:
    result = C2Result(status="ERROR")
    try:
        req = C2Input.model_validate(value.model_dump(mode="json") if isinstance(value, C2Input) else value)
        result.source_fingerprint=fingerprint(req.source)
        result.target_fingerprint=fingerprint(req.target)
        result.stage="STATIC_RESOURCE_PREFLIGHT"
        p, lineage = build_c2_problem(req)
        result.placement_problem = p
        result.output_fingerprint = lineage["problem"]
        result.source_unchanged = fingerprint(req.source)==result.source_fingerprint
    except C2Failure as e:
        result.status = "UNSUPPORTED" if e.unsupported else ("INFEASIBLE" if e.infeasible else "INVALID_INPUT")
        result.proof_scope = "FIXED_O1_C2" if e.infeasible else "NONE"
        result.findings=[str(e)]
        return result
    except (ValidationError, HandoffError, ValueError, TypeError) as e:
        result.status = "INVALID_INPUT"
        result.findings = [str(e)]
        return result
    except Exception as e:
        result.status="ERROR"
        result.findings=[f"C2_COMPILATION_ERROR: {type(e).__name__}: {e}"]
        return result
    if time_limit_seconds <= 0:
        result.status="UNKNOWN"
        result.stage="PLACEMENT"
        result.findings=["No solver search budget; no feasibility or impossibility proof"]
        return result
    result.stage="PLACEMENT"
    try:
        solved = solve_placement(p, {"max_time_seconds":time_limit_seconds})
        result.solver_status=solved.solver_status
        if solved.status == "FEASIBLE" and solved.candidate is not None:
            # C1 already performed independent hard validation; do it once more
            # after extraction and verify the accepted options remained pinned.
            checked = review_core(p,solved.candidate)
            if checked.result != "CANDIDATE_HARD_VALIDATED":
                result.status="ERROR"
                result.independent_hard_validation="FAILED"
                result.findings=["C2_INDEPENDENT_CHECKER_DISAGREEMENT: withheld candidate"]
                return result
            if result.source_fingerprint != fingerprint(req.source):
                result.status="ERROR";result.findings=["O1_SOURCE_CHANGED_DURING_SOLVE"]
                return result
            event_map = {e.id:e for e in p.events}
            for e in solved.candidate.event_assignments:
                allocations = {a.requirement_id:a.resource_ids for a in e.resource_allocations}
                for reqt in event_map[e.event_id].requirements:
                    selection = allocations.get(reqt.id,[])
                    if reqt.role=="TEACHER" and len(selection)==1:result.teacher_assignments[e.event_id]=selection[0]
                    if reqt.role=="ROOM" and len(selection)==1:result.room_assignments[e.event_id]=selection[0]
            if len(result.teacher_assignments) != len(p.events) or len(result.room_assignments) != len(p.events):
                result.status="ERROR";result.findings=["INCOMPLETE_TEACHER_OR_ROOM_SELECTION"]
                result.teacher_assignments={};result.room_assignments={}
                return result
            result.candidate=solved.candidate
            result.status="FEASIBLE"
            result.independent_hard_validation="PASSED"
            result.event_count=len(solved.candidate.event_assignments)
            result.stage="DONE"
            return result
        if solved.status == "INFEASIBLE":
            result.status="INFEASIBLE";result.proof_scope="FIXED_O1_C2"
            result.findings=["C1_PROVED_INFEASIBLE: fixed accepted O1 allocations cannot be taught under the supplied C2 time/teacher/room rules"]
        elif solved.status == "UNKNOWN":
            result.status="UNKNOWN";result.findings=["Search unresolved; no infeasibility proof"]
        elif solved.status in ("INVALID_INPUT", "UNSUPPORTED"):
            result.status=solved.status
            result.findings=solved.findings
        else:
            result.status="ERROR";result.findings=solved.findings
        return result
    except Exception as e:
        result.status="ERROR";result.findings=[f"C2_RUNTIME_ERROR: {type(e).__name__}: {e}"]
        return result
