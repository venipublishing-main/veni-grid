from __future__ import annotations
from copy import deepcopy
from itertools import product
import json, os, random, subprocess, sys
import pytest
from veni_grid_contract.core_v1 import CoreProblem, CoreWitness, core_witness_errors
from veni_grid_solver import solve
from .helpers import base, raw, rule, pin


def options_model(people=1, capacity=1):
    p=raw(base(2))
    p['activities']=[{'id':'activity:choice','label':'Choice','demand':{'basis':'PER_ENROLLED','unit':'WINDOWS','amount':1}}]
    p['offerings']=[];p['participation_requests']=[]
    for i,e in enumerate(p['events']):
        e.update(activity_id='activity:choice',offering_id=f'offering:O{i}',required=False,fixed_participant_ids=[])
        p['offerings'].append({'id':f'offering:O{i}','activity_id':'activity:choice','event_ids':[e['id']],'capacity':capacity})
    for i in range(people):
        p['participation_requests'].append({'id':f'request:R{i}','participant_id':f'pupil:P{i}','activity_id':'activity:choice',
             'eligible_offering_ids':['offering:O0','offering:O1']})
    return p


def test_section_selection_is_computed_and_unused_event_stays_off():
    p=options_model();p['events'][0]['requirements'][0]['eligible_resource_ids']=['teacher:A']
    p['constraints']=[rule('EXCLUDE_RESOURCE_FROM_EVENT',event_ids=['event:E0'],resource_ids=['teacher:A'])]
    r=solve(p);assert r.status=='FEASIBLE',r.findings
    assert r.candidate.enrollment_assignments[0].offering_ids==['offering:O1']
    assert [e.event_id for e in r.candidate.event_assignments]==['event:E1']


def test_capacity_forces_two_sections_then_teacher_time_makes_infeasible():
    p=options_model(2,1)
    for i in range(2):pin(p,i,'win:D1P1','teacher:A',f'room:R{i}')
    assert solve(p).status=='INFEASIBLE'
    p['events'][1]['requirements'][0]['eligible_resource_ids']=['teacher:B']
    r=solve(p);assert r.status=='FEASIBLE'
    assert len(r.candidate.event_assignments)==2


def test_duplicate_requests_same_person_do_not_double_count_section_capacity():
    p=options_model();p['participation_requests'][0]['eligible_offering_ids']=['offering:O0']
    q=deepcopy(p['participation_requests'][0]);q['id']='request:duplicate-person';p['participation_requests'].append(q)
    r=solve(p);assert r.status=='FEASIBLE'
    assert len(r.candidate.enrollment_assignments)==2 and len(r.candidate.event_assignments)==1


def test_optional_continuity_does_not_activate_unused_section():
    p=options_model();p['participation_requests'][0]['eligible_offering_ids']=['offering:O0']
    p['events'][0]['requirements'][0]['eligible_resource_ids']=['teacher:A']
    p['events'][1]['requirements'][0]['eligible_resource_ids']=['teacher:B']
    p['constraints']=[rule('RESOURCE_CONTINUITY',allocations=[{'event_id':'event:E0','requirement_id':'req:T0'},
                                                          {'event_id':'event:E1','requirement_id':'req:T1'}])]
    r=solve(p);assert r.status=='FEASIBLE'
    assert len(r.candidate.event_assignments)==1


def test_per_enrolled_curriculum_mismatch_cannot_be_selected():
    p=options_model();p['activities'][0]['demand']['amount']=2
    assert solve(p).status=='INFEASIBLE'


def test_enrolled_learner_clash_not_hidden_by_different_sections():
    p=options_model();q=p['participation_requests'][0];q['min_select']=q['max_select']=2
    pin(p,0,'win:D1P1','teacher:A','room:R0');pin(p,1,'win:D1P1','teacher:B','room:R1')
    assert solve(p).status=='INFEASIBLE'


def test_soft_unmet_request_does_not_force_an_infeasible_section():
    p=options_model();p['participation_requests'][0]['strength']='SOFT'
    p['activities'][0]['demand']['amount']=2 # cannot satisfy either selected offering
    r=solve(p);assert r.status=='FEASIBLE'
    assert r.candidate.enrollment_assignments[0].offering_ids==[]
    assert r.soft_request_ids==['request:R0'] and r.soft_scoring=='NOT_PERFORMED'


def tiny_oracle(p):
    """Exhaustive independent witness enumeration. Used ONLY in small tests."""
    possibilities=[]
    for e in p.events:
        roles=[list(__import__('itertools').combinations(q.eligible_resource_ids,q.quantity)) for q in e.requirements]
        choices=[]
        for wid, selected in product(e.placement.start_window_ids, product(*roles)):
            choices.append({'event_id':e.id,'start_window_id':wid,
                            'resource_allocations':[{'requirement_id':q.id,'resource_ids':list(ids)} for q,ids in zip(e.requirements,selected)]})
        possibilities.append(choices)
    for assignments in product(*possibilities):
        w=CoreWitness(solution_id='solution:oracle',problem_id=p.problem_id,model_version=p.model_version,status='FEASIBLE',
                      event_assignments=list(assignments))
        if not core_witness_errors(p,w):return True
    return False


def random_tiny(seed):
    rng=random.Random(seed);p=raw(base())
    starts=['win:D1P1','win:D1P2']
    for e in p['events']:
        e['placement']['start_window_ids']=rng.sample(starts,rng.randint(1,2))
        for q in e['requirements']:
            q['eligible_resource_ids']=rng.sample(q['eligible_resource_ids'],rng.randint(1,2))
    if rng.random()<0.4:p['events'][1]['fixed_participant_ids']=p['events'][0]['fixed_participant_ids'][:]
    for r in p['resources']:
        if rng.random()<0.18:r['unavailable_window_ids']=[rng.choice(starts)]
    kinds=['MAX_DAILY_MINUTES','EVENT_BEFORE','EVENT_NOT_SAME_TIME','EVENT_SAME_START','RESOURCE_CONTINUITY','WORKLOAD_BALANCE']
    kind=rng.choice(kinds)
    if kind=='MAX_DAILY_MINUTES':p['constraints']=[rule(kind,resource_ids=['teacher:A','teacher:B'],limit_minutes=rng.choice([29,30,60]))]
    elif kind=='EVENT_BEFORE':p['constraints']=[rule(kind,earlier_event_id='event:E0',later_event_id='event:E1',minimum_gap_minutes=rng.choice([0,15,16]))]
    elif kind in ['EVENT_NOT_SAME_TIME','EVENT_SAME_START']:p['constraints']=[rule(kind,event_ids=['event:E0','event:E1'])]
    elif kind=='RESOURCE_CONTINUITY':p['constraints']=[rule(kind,allocations=[{'event_id':'event:E0','requirement_id':'req:T0'}, {'event_id':'event:E1','requirement_id':'req:T1'}])]
    elif kind=='WORKLOAD_BALANCE':p['constraints']=[rule(kind,resource_ids=['teacher:A','teacher:B'],metric=rng.choice(['ASSIGNMENT_COUNT','DUTY_MINUTES']),target_spread=rng.choice([0,1,30]))]
    return CoreProblem.model_validate(p)


@pytest.mark.parametrize('seed',range(80))
def test_small_complete_oracle_agrees_with_cp_sat(seed):
    p=random_tiny(seed);exists=tiny_oracle(p);r=solve(p)
    assert r.status==('FEASIBLE' if exists else 'INFEASIBLE'),(seed,exists,r.model_dump())


def test_result_is_stable_across_python_hash_seeds():
    code="""import json
from tests_solver.helpers import rule_case
from veni_grid_solver import solve
r=solve(rule_case('TRAVEL_TIME'))
print(json.dumps({'candidate':r.candidate.model_dump(mode='json'),'model':r.compiled_model_hash},sort_keys=True))
"""
    outs=[]
    for seed in ['1','42']:
        env=dict(os.environ,PYTHONHASHSEED=seed)
        outs.append(subprocess.check_output([sys.executable,'-c',code],env=env,text=True))
    assert outs[0]==outs[1]
