from __future__ import annotations
import copy
import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from jsonschema import Draft202012Validator
from veni_grid_contract.models import SchedulingProblem,SchedulingSolution
from veni_grid_contract.validation import problem_issues,witness_issues

ROOT=Path(__file__).resolve().parents[1]
CASES=['master_school','learner_choices','invigilation']

def sample(case):
    root=ROOT/'fixtures'/case
    return (json.loads((root/'problem.json').read_text()),
            json.loads((root/'solution-witness.json').read_text()))

def validate(problem,solution):
    return witness_issues(SchedulingProblem.model_validate(problem),SchedulingSolution.model_validate(solution))

def codes(issues):return {issue.code for issue in issues}

@pytest.mark.parametrize('case',CASES)
def test_example_json_schema_contract(case):
    p,s=sample(case)
    for path,data in [('scheduling-problem',p),('scheduling-solution',s)]:
        schema=json.loads((ROOT/'schemas'/f'{path}.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(data)

@pytest.mark.parametrize('case',CASES)
def test_valid_cross_vertical_witness(case):
    p,s=sample(case)
    assert problem_issues(SchedulingProblem.model_validate(p)) == []
    assert validate(p,s) == []

def test_strict_envelope_no_undocumented_fields():
    p,_=sample('master_school');p['undocumented_solver_magic']=True
    with pytest.raises(ValidationError):SchedulingProblem.model_validate(p)

def test_bad_link_is_rejected():
    p,_=sample('master_school');p['events'][0]['activity_id']='act:unknown'
    assert 'UNKNOWN_ACTIVITY' in codes(problem_issues(SchedulingProblem.model_validate(p)))

def test_duplicate_global_entity_id_is_rejected():
    p,_=sample('master_school');p['resources'][0]['id']=p['events'][0]['id']
    assert 'DUPLICATE_GLOBAL_ID' in codes(problem_issues(SchedulingProblem.model_validate(p)))

def test_group_membership_cycle_is_rejected():
    p,_=sample('master_school');p['resources'].append({'id':'res:group:LOOP1','kind':'GROUP','label':'Loop 1','member_ids':['res:group:LOOP2']})
    p['resources'].append({'id':'res:group:LOOP2','kind':'GROUP','label':'Loop 2','member_ids':['res:group:LOOP1']})
    assert 'GROUP_CYCLE' in codes(problem_issues(SchedulingProblem.model_validate(p)))

def test_missing_required_school_event_is_detected():
    p,s=sample('master_school');s['event_assignments'].pop()
    assert 'MISSING_EVENT' in codes(validate(p,s))

def test_manual_event_lock_cannot_be_silently_bypassed():
    p,s=sample('master_school')
    p['events'][0]['placement']['start_window_ids'].append('win:4:standard:2')
    s['event_assignments'][0]['start_window_id']='win:4:standard:2'
    assert 'LOCK_START_VIOLATED' in codes(validate(p,s))

def test_double_period_crossing_bad_gap_is_rejected():
    p,s=sample('master_school')
    p['events'][4]['duration']['max_gap_minutes']=0
    assert 'INVALID_PLACEMENT' in codes(validate(p,s))

def test_teacher_double_booking_is_rejected():
    p,s=sample('master_school')
    p['events'][2]['placement']['start_window_ids'].append('win:1:standard:1')
    s['event_assignments'][2]['start_window_id']='win:1:standard:1'
    assert 'RESOURCE_OVERLAP' in codes(validate(p,s))

def test_room_capacity_is_enforced():
    p,s=sample('master_school')
    # All four combined class members must fit in assembly hall.
    next(r for r in p['resources'] if r['id']=='res:room:HALL')['capacity']=3
    assert 'ROOM_OVER_CAPACITY' in codes(validate(p,s))

def test_elective_sections_cannot_overfill():
    p,s=sample('learner_choices')
    r=next(r for r in s['enrollment_assignments'] if r['request_id']=='req:S3PHY')
    r['offering_ids']=['offer:PHYA']
    next(o for o in p['offerings'] if o['id']=='offer:PHYA')['capacity']=1
    assert 'OFFERING_OVER_CAPACITY' in codes(validate(p,s))

def test_cross_bell_overlap_is_detected_for_one_student():
    p,s=sample('learner_choices')
    # PHYC on day 2 regular bell at 08:55; ART moves to day 2 seminar 08:30.
    # Labels, sequence and bell_id differ, real-time minute ranges still overlap.
    art=next(a for a in s['event_assignments'] if a['event_id']=='evt:ARTA')
    art['start_window_id']='win:2:seminar:1'
    issue_list=validate(p,s)
    assert 'RESOURCE_OVERLAP' in codes(issue_list)
    assert any('res:person:S3' in x.message for x in issue_list if x.code=='RESOURCE_OVERLAP')

def test_invigilator_overlap_across_partially_overlapping_sessions():
    p,s=sample('invigilation')
    lang=next(a for a in s['event_assignments'] if a['event_id']=='evt:EX_L')
    lang['resource_allocations'][0]['resource_ids']=['res:person:I2']
    assert 'RESOURCE_OVERLAP' in codes(validate(p,s))

def test_invigilator_exclusion_hard_rule_is_enforced():
    p,s=sample('invigilation')
    math=next(a for a in s['event_assignments'] if a['event_id']=='evt:EX_M')
    math['resource_allocations'][0]['resource_ids']=['res:person:I1','res:person:I4']
    assert 'EXCLUSION_VIOLATED' in codes(validate(p,s))

def test_invigilation_daily_max_duration_is_enforced():
    p,s=sample('invigilation')
    # Give I1 Math and Language, exceeding 180 min. Also creates a time clash.
    lang=next(a for a in s['event_assignments'] if a['event_id']=='evt:EX_L')
    lang['resource_allocations'][0]['resource_ids']=['res:person:I1']
    assert 'DAILY_LOAD_VIOLATED' in codes(validate(p,s))

def test_staff_unavailable_from_active_blackout_is_enforced():
    p,s=sample('invigilation')
    # Actual blackout is the 13:00–15:00 session; lang exam 10:30–13:00 does not collide.
    # Move blackout to AM, so Math invigilator I2 becomes unavailable.
    blackout=next(c for c in p['constraints'] if c['kind']=='RESOURCE_BLACKOUT')
    blackout['window_ids']=['win:1:exam:1']
    assert 'BLACKOUT_VIOLATED' in codes(validate(p,s))

def test_solution_cannot_claim_to_be_its_own_validator():
    p,s=sample('master_school');s['validation']='PASSED'
    assert 'UNTRUSTED_SELF_VALIDATION' in codes(validate(p,s))

def test_stale_solution_version_is_rejected():
    p,s=sample('master_school');s['model_version']=2
    assert 'STALE_SOLUTION' in codes(validate(p,s))

def test_global_activity_demand_must_match_events():
    p,_=sample('master_school')
    p['activities'][0]['demand']['amount']=999
    assert 'GLOBAL_DEMAND_MISMATCH' in codes(problem_issues(SchedulingProblem.model_validate(p)))

def test_unsupported_rule_name_fails_closed():
    p,_=sample('master_school')
    p['constraints'].append({'id':'rule:unknown','kind':'ARBITRARY_PYTHON_SCRIPT','strength':'HARD','source':'USER'})
    with pytest.raises(ValidationError):SchedulingProblem.model_validate(p)

def test_no_false_infeasibility_from_unknown_solution():
    p,s=sample('master_school')
    s['status']='UNKNOWN';s['event_assignments']=[]
    assert 'NOT_A_WITNESS' in codes(validate(p,s))


def test_one_candidate_offering_may_remain_inactive():
    p,s=sample('learner_choices')
    assert any(o['id']=='offer:PHYD' for o in p['offerings'])
    assert not any(a['event_id']=='evt:PHYD' for a in s['event_assignments'])
    assert validate(p,s) == []

def test_soft_request_can_be_unmet_without_failing_hard_feasibility():
    p,s=sample('learner_choices')
    request=next(r for r in p['participation_requests'] if r['id']=='req:S3ART')
    request['strength']='SOFT'
    response=next(r for r in s['enrollment_assignments'] if r['request_id']=='req:S3ART')
    response['offering_ids']=[]
    s['event_assignments']=[a for a in s['event_assignments'] if a['event_id']!='evt:ARTA']
    assert validate(p,s) == []

def test_same_real_date_cannot_be_split_into_unconnected_day_keys():
    p,_=sample('invigilation')
    p['days'][1]['date']=p['days'][0]['date']
    assert 'DUPLICATE_DATED_DAY' in codes(problem_issues(SchedulingProblem.model_validate(p)))

def test_invalid_timezone_rejected_by_semantic_gate():
    p,_=sample('invigilation')
    p['timezone']='Planet/Mars'
    assert 'BAD_TIMEZONE' in codes(problem_issues(SchedulingProblem.model_validate(p)))
