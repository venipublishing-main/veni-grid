"""C2: real O1-generated learner choices to teacher/lab/time C1 CP-SAT tests.

Every ID is synthetic and no live school timetable is touched.
"""
from __future__ import annotations
from collections import Counter, defaultdict
import pytest

from scripts.run_c2_probes import school_input, large_school_room_shortage_input, large_school_teacher_shortage_input
from veni_grid_contract.handoff_common import fingerprint
from veni_grid_contract.option_design import option_errors
from veni_grid_contract.conformance import review_core
from veni_grid_contract.core_v1 import QualificationRule, ContinuityRule
from veni_grid_contract.models import RuleSource
from veni_grid_integration import solve_c2, build_c2_problem


def test_actual_o1_c1_generated_sections_acquire_valid_qualified_teachers_and_rooms():
    req=school_input()
    before=fingerprint(req.source)
    p,lineage=build_c2_problem(req)
    assert not option_errors(req.source.demand,req.source.plan)
    assert len(p.events)==18 and len(p.offerings)==9
    assert len(p.participation_requests)==48
    assert sum(len(e.requirements) for e in p.events)==36
    assert sum(isinstance(x,QualificationRule) for x in p.constraints)==9
    assert sum(isinstance(x,ContinuityRule) for x in p.constraints)==9
    assert lineage['source']==req.source_ref.content_sha256
    result=solve_c2(req,time_limit_seconds=10)
    assert result.status=='FEASIBLE',result.findings
    assert result.stage=='DONE' and result.event_count==18
    assert result.independent_hard_validation=='PASSED'
    assert result.source_unchanged and before==fingerprint(req.source)
    assert result.quality_optimisation=='NOT_PERFORMED'
    assert result.organisation_wide_clashes=='NOT_ASSESSED'
    assert result.publication=='NOT_GRANTED'
    assert len(result.teacher_assignments)==18 and len(result.room_assignments)==18
    assert result.candidate and review_core(result.placement_problem,result.candidate).result=='CANDIDATE_HARD_VALIDATED'
    event_map={e.id:e for e in result.placement_problem.events}
    resources={r.id:r for r in result.placement_problem.resources}
    qualifications={(c.resource_id,c.competency) for c in result.placement_problem.credentials}
    requested={rq.id:rq for rq in result.placement_problem.participation_requests}
    enrolled={e.request_id:e.offering_ids for e in result.candidate.enrollment_assignments}
    assert len(enrolled)==48 and all(enrolled[rid]==req.eligible_offering_ids for rid,req in requested.items())
    section_sizes=Counter(oid for selected in enrolled.values() for oid in selected)
    acts={a.id:a for a in result.placement_problem.activities}
    teacher_by_section=defaultdict(set)
    for eid,person in result.teacher_assignments.items():
        event=event_map[eid]
        family_label=acts[event.activity_id].label
        assert person==f'person:T{family_label[-1]}'
        assert 'TEACHER' in resources[person].tags
        assert (person,'competency:'+family_label[-1]) in qualifications
        teacher_by_section[event.offering_id].add(person)
    assert all(len(choices)==1 for choices in teacher_by_section.values())
    for eid,room in result.room_assignments.items():
        event=event_map[eid]
        assert resources[room].kind=='SPACE'
        assert resources[room].capacity>=section_sizes[event.offering_id]
        if acts[event.activity_id].label.endswith('D'):
            assert 'LAB' in resources[room].tags


@pytest.mark.parametrize('case,code',[
    ('no_science_qualification','BLOCK_TEACHER_SHORTAGE'),
    ('wrong_teacher','BLOCK_TEACHER_SHORTAGE'),
    ('remove_lab','BLOCK_CLASSROOM_SHORTAGE'),
    ('reduce_lab_capacity','BLOCK_CLASSROOM_SHORTAGE'),
    ('too_few_rooms','BLOCK_CLASSROOM_SHORTAGE'),
])
def test_static_matching_proves_fixed_plan_not_teachable(case,code):
    result=solve_c2(school_input(**{case:True}))
    assert result.status=='INFEASIBLE'
    assert result.stage=='STATIC_RESOURCE_PREFLIGHT'
    assert result.proof_scope=='FIXED_O1_C2'
    assert code in result.findings[0]
    assert result.candidate is None


def test_time_specific_teacher_unavailability_is_proved_by_actual_c1_cp_sat():
    result=solve_c2(school_input(teacher_science_blackout=True),time_limit_seconds=10)
    assert result.status=='INFEASIBLE',result.findings
    assert result.stage=='PLACEMENT' and result.proof_scope=='FIXED_O1_C2'
    assert result.solver_status=='INFEASIBLE'
    assert result.candidate is None and 'C1_PROVED_INFEASIBLE' in result.findings[0]


def test_stale_o1_source_fingerprint_rejected_before_schedule():
    req=school_input();req=req.model_copy(deep=True)
    req.source_ref.content_sha256='0'*64
    r=solve_c2(req)
    assert r.status=='INVALID_INPUT' and r.stage=='STATIC_RESOURCE_PREFLIGHT'
    assert 'SOURCE_CONTENT_MISMATCH' in r.findings[0]


def test_unaccepted_o1_plan_refused():
    req=school_input();req=req.model_copy(deep=True)
    req.source_ref.state='DRAFT'
    r=solve_c2(req)
    assert r.status=='INVALID_INPUT' and 'SOURCE_NOT_ACCEPTED' in r.findings[0]


def test_unrecognised_teacher_identity_rejected_not_guessed():
    req=school_input();req=req.model_copy(deep=True)
    req.target.family_teaching[0].teacher_ids=['person:unknown']
    r=solve_c2(req)
    assert r.status=='INVALID_INPUT' and 'UNKNOWN_TEACHER' in r.findings[0]


def test_shared_cumulative_hall_explicitly_unsupported_not_falsely_infeasible():
    req=school_input();req=req.model_copy(deep=True)
    lab=next(r for r in req.target.resources if r.id=='space:LAB')
    lab.sharing_mode='CUMULATIVE'
    r=solve_c2(req)
    assert r.status=='UNSUPPORTED'
    assert 'SHARED_SPACE_UNSUPPORTED' in r.findings[0]


def test_calendar_credential_needs_dates_not_guess_on_cycle():
    from veni_grid_contract.primitives import Interval
    from datetime import datetime,timezone
    req=school_input();req=req.model_copy(deep=True)
    req.target.credentials[0].valid_during=Interval(start=datetime(2026,1,1,tzinfo=timezone.utc),
                                                  end=datetime(2027,1,1,tzinfo=timezone.utc))
    r=solve_c2(req)
    assert r.status=='UNSUPPORTED' and 'DATED_QUALIFICATION_ON_CYCLE' in r.findings[0]


def test_zero_time_budget_is_unknown_after_valid_preflight():
    r=solve_c2(school_input(),time_limit_seconds=0)
    assert r.status=='UNKNOWN' and r.candidate is None
    assert r.proof_scope=='NONE' and r.stage=='PLACEMENT'


def test_any_unspecified_soft_constraint_is_not_silently_ignored():
    from veni_grid_contract.models import ActivitySpread,RuleStrength
    req=school_input();req=req.model_copy(deep=True)
    req.target.constraints.append(ActivitySpread(id='rule:soft:subject',source=RuleSource.USER,strength=RuleStrength.SOFT,
                                                activity_ids=['activity:nonexistent'],minimum_distinct_days=2))
    r=solve_c2(req)
    assert r.status=='UNSUPPORTED' and 'UNSCORED_SOFT_RULE' in r.findings[0]


def test_accepted_o1_selection_is_fixed_in_converted_core():
    req=school_input();p,_=build_c2_problem(req)
    original={x.request_id:x.offering_id for x in req.source.plan.allocations}
    for rq in p.participation_requests:
        assert rq.strength=='HARD'
        assert len(rq.eligible_offering_ids)==1
    assert len(original)==len(p.participation_requests)
    assert all(e.required is False and e.offering_id for e in p.events)


def test_out_of_scope_linked_commitments_are_never_claimed_validated():
    result=solve_c2(school_input(),time_limit_seconds=6)
    assert result.organisation_wide_clashes=='NOT_ASSESSED'
    assert result.quality_optimisation=='NOT_PERFORMED'
    assert result.publication=='NOT_GRANTED'


def test_1500_learner_o1_plan_reports_concurrent_room_capacity_bottleneck():
    request=large_school_room_shortage_input()
    assert len(request.source.demand.requests)==9000
    assert len(request.source.plan.offerings)==360
    result=solve_c2(request)
    assert result.status=='INFEASIBLE'
    assert result.proof_scope=='FIXED_O1_C2' and result.stage=='STATIC_RESOURCE_PREFLIGHT'
    assert '30 of 60 simultaneous sections' in result.findings[0]
    assert 'BLOCK_CLASSROOM_SHORTAGE' in result.findings[0]
    assert result.candidate is None
    assert result.publication=='NOT_GRANTED'


def test_cross_day_teacher_continuity_is_enforced_not_just_first_valid_teaching_day():
    from veni_grid_contract.core_v1 import LocatedResource, Credential
    req=school_input();req=req.model_copy(deep=True)
    staff=next(r for r in req.target.resources if r.id=='person:TA')
    staff.unavailable_window_ids=[w.id for w in req.target.windows if w.day_id=='day:D2']
    req.target.resources.append(LocatedResource(id='person:TA2',kind='PERSON',label='Invented backup A teacher',
        tags=['TEACHER'],unavailable_window_ids=[w.id for w in req.target.windows if w.day_id=='day:D1']))
    req.target.credentials.append(Credential(id='credential:TA2',resource_id='person:TA2',
        competency='competency:A',source_ref='synthetic:registry'))
    a=next(f for f in req.target.family_teaching if f.family_id=='family:A')
    a.teacher_ids.append('person:TA2')
    unavailable=solve_c2(req,time_limit_seconds=10)
    assert unavailable.status=='INFEASIBLE' and unavailable.proof_scope=='FIXED_O1_C2'
    a.same_teacher_across_occurrences=False
    feasible=solve_c2(req,time_limit_seconds=10)
    assert feasible.status=='FEASIBLE',feasible.findings
    assert feasible.independent_hard_validation=='PASSED'


def test_dated_expired_teacher_qualification_is_not_validated_as_permanent():
    from veni_grid_contract.primitives import Interval
    from datetime import date,datetime,timezone
    req=school_input();req=req.model_copy(deep=True)
    req.target.days[0].date=date(2026,11,16)
    req.target.days[1].date=date(2026,11,17)
    cert=next(c for c in req.target.credentials if c.resource_id=='person:TD')
    cert.valid_during=Interval(start=datetime(2026,11,15,tzinfo=timezone.utc),
                                end=datetime(2026,11,17,tzinfo=timezone.utc))
    r=solve_c2(req,time_limit_seconds=10)
    assert r.status=='INFEASIBLE' and r.stage=='PLACEMENT'
    assert r.proof_scope=='FIXED_O1_C2'


def test_explicit_occurrence_day_cannot_silently_be_mapped_elsewhere():
    req=school_input();req=req.model_copy(deep=True)
    block=req.target.block_windows[0]
    block.allowed_day_ids=['day:D2']
    r=solve_c2(req)
    assert r.status=='INVALID_INPUT' and 'BLOCK_WINDOW_DAY_MISMATCH' in r.findings[0]


def test_large_o1_plan_with_many_rooms_but_only_30_qualified_teachers_fails():
    request=large_school_teacher_shortage_input()
    assert len(request.source.demand.requests)==9000
    assert len(request.source.plan.offerings)==360
    result=solve_c2(request)
    assert result.status=='INFEASIBLE' and result.stage=='STATIC_RESOURCE_PREFLIGHT'
    assert 'BLOCK_TEACHER_SHORTAGE' in result.findings[0]
    assert '30 of 60 simultaneous sections' in result.findings[0]
    assert result.proof_scope=='FIXED_O1_C2'


def test_specialist_room_hall_set_shortage_even_with_three_total_rooms():
    req=school_input();req=req.model_copy(deep=True)
    # A and D both require the *one* lab in a block containing A, C, D.
    # Counting three rooms for three sections would miss the specialist trap.
    a=next(t for t in req.target.family_teaching if t.family_id=='family:A')
    a.room_ids=['space:LAB'];a.required_room_tags=['LAB']
    result=solve_c2(req)
    assert result.status=='INFEASIBLE'
    assert result.proof_scope=='FIXED_O1_C2'
    assert 'BLOCK_CLASSROOM_SHORTAGE' in result.findings[0]
    assert 'only 2 of 3 simultaneous sections' in result.findings[0]


def test_requested_same_room_continuity_across_school_days_is_hard_enforced():
    req=school_input();req=req.model_copy(deep=True)
    a=next(t for t in req.target.family_teaching if t.family_id=='family:A')
    a.same_room_across_occurrences=True
    r=solve_c2(req,time_limit_seconds=10)
    assert r.status=='FEASIBLE',r.findings
    sections=defaultdict(set)
    events={e.id:e for e in r.placement_problem.events}
    subjects={a.id:a.label for a in r.placement_problem.activities}
    for event_id,room_id in r.room_assignments.items():
        if subjects[events[event_id].activity_id].endswith('A'):
            sections[events[event_id].offering_id].add(room_id)
    assert len(sections)==2
    assert all(len(rooms)==1 for rooms in sections.values())
    assert any(isinstance(rule,ContinuityRule) for rule in r.placement_problem.constraints)
