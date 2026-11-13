"""Demand-first O1 construction: no prepared sections, no upstream timetable."""
from __future__ import annotations
from collections import Counter, defaultdict
from copy import deepcopy
from random import Random
import pytest
from scripts.build_benchmark_c0 import build as c0_build
from scripts.build_benchmark_c1 import build as c1_build
from veni_grid_contract.option_design import OptionDesignProblem, option_errors
from veni_grid_options import OptionSolveOptions, solve_options


def triangle(*,sections=2,maximum=2,minimum=1,blocks=2):
    edges=[('S1','A','B'),('S2','B','C'),('S3','A','C')]
    families=[{'id':f'family:{x}','label':x,'min_members':minimum,
               'max_members':maximum,'max_sections':sections} for x in 'ABC']
    requests=[{'id':f'request:{s}:{f}','participant_id':f'person:{s}',
               'family_id':f'family:{f}'} for s,a,b in edges for f in (a,b)]
    return OptionDesignProblem.model_validate({'problem_id':'test:triangle','model_version':1,
        'participant_ids':[f'person:{s}' for s,_,_ in edges],
        'families':families,'requests':requests,'max_blocks':blocks})


def check_complete(p,r):
    assert r.status=='FEASIBLE',r.findings
    assert r.witness and r.independent_validation=='PASSED'
    assert r.generated_sections and r.request_count==len(p.requests)
    assert r.allocations==len(p.requests)
    assert not option_errors(p,r.witness)
    assert r.staffing_and_rooms=='NOT_MODELLED'
    assert r.lesson_placement=='NOT_MODELLED'
    assert r.publication=='NOT_GRANTED'
    families={f.id:f for f in p.families}
    by_o=Counter(a.offering_id for a in r.witness.allocations)
    for o in r.witness.offerings:
        f=families[o.family_id]
        assert f.min_members <= by_o[o.id] <= f.max_members
    by_f=Counter(o.family_id for o in r.witness.offerings)
    for fid,n in by_f.items():assert n<=families[fid].max_sections


def test_c0_1500_people_9000_requests_no_sections_given_to_solver():
    p,provided=c0_build()
    before=p.model_dump_json()
    r=solve_options(p,{'max_time_seconds':10})
    check_complete(p,r)
    assert len(p.participant_ids)==1500 and len(p.requests)==9000
    assert r.profile=='SINGLE_FAMILY_BLOCK'
    assert r.block_count==6 and r.offering_count==360
    assert len(provided.offerings)==450 # supplied C0 witness is NOT copied
    assert r.block_optimality_scope=='SINGLE_BLOCK_ONLY'
    assert r.min_block_count_proven
    assert before==p.model_dump_json()


def test_c0_reproducible_when_request_order_changes():
    p,_=c0_build()
    a=solve_options(p,{'max_time_seconds':8})
    p2=p.model_copy(deep=True)
    Random(2026).shuffle(p2.requests)
    b=solve_options(p2,{'max_time_seconds':8})
    check_complete(p2,b)
    assert a.witness.model_dump(mode='json')==b.witness.model_dump(mode='json')


def test_single_block_family_triangle_is_profile_only_infeasible():
    p=triangle()
    r=solve_options(p,{'strategy':'SINGLE_FAMILY_BLOCK','max_time_seconds':4})
    assert r.status=='INFEASIBLE' and r.profile=='SINGLE_FAMILY_BLOCK'
    assert r.proof_scope=='SINGLE_BLOCK_ONLY' and r.witness is None
    assert r.stages[0]['solver_status']=='INFEASIBLE'


def test_flexible_triangle_auto_recovers_from_single_block_conflict():
    p=triangle()
    r=solve_options(p,{'max_time_seconds':7})
    check_complete(p,r)
    assert r.profile=='FLEXIBLE_SECTIONS' and r.block_count==2
    assert r.min_block_count_proven and r.block_optimality_scope=='FULL_O1'
    assert len(r.witness.offerings)>=4
    blocks_by_family=defaultdict(set)
    for o in r.witness.offerings:blocks_by_family[o.family_id].add(o.block_id)
    assert any(len(v)>1 for v in blocks_by_family.values())


def test_flexible_profile_direct_same_solution_valid():
    p=triangle()
    r=solve_options(p,{'strategy':'FLEXIBLE_SECTIONS','max_time_seconds':7})
    check_complete(p,r)
    assert r.block_count==2 and r.min_section_count_proven


def test_triangle_with_only_one_section_per_family_proves_full_o1_impossible():
    p=triangle(sections=1,minimum=2,maximum=2)
    r=solve_options(p,{'max_time_seconds':6})
    assert r.status=='INFEASIBLE' and r.proof_scope=='FULL_O1'
    assert r.witness is None and r.stages[-1]['solver_status']=='INFEASIBLE'


def test_c1_crossed_subject_choices_no_preassigned_blocks():
    p=c1_build(repeats=4)
    assert len(p.participant_ids)==16 and len(p.requests)==48
    r=solve_options(p,{'max_time_seconds':10})
    check_complete(p,r)
    assert r.profile=='FLEXIBLE_SECTIONS'
    assert r.block_count==3 and r.min_block_count_proven


def test_learner_request_count_greater_than_blocks_proven_impossible():
    p=triangle();p=p.model_copy(deep=True)
    p.max_blocks=1
    r=solve_options(p,{'max_time_seconds':3})
    assert r.status=='INFEASIBLE' and r.proof_scope=='FULL_O1'


def test_insufficient_section_capacity_proven_impossible():
    p=triangle();p=p.model_copy(deep=True)
    for f in p.families:
        f.max_sections=1;f.max_members=1
    r=solve_options(p)
    assert r.status=='INFEASIBLE' and r.proof_scope=='FULL_O1'


def test_too_few_students_for_min_section_size_proven_impossible():
    p=triangle();p=p.model_copy(deep=True)
    p.families[0].min_members=3;p.families[0].max_members=4
    r=solve_options(p)
    assert r.status=='INFEASIBLE' and r.proof_scope=='FULL_O1'

@pytest.mark.parametrize('case',['bad-person','bad-family','repeat-request','repeat-pair','repeat-person','repeat-family'])
def test_bad_input_rejected_before_solver(case):
    p=triangle();p=p.model_copy(deep=True)
    if case=='bad-person':p.requests[0].participant_id='person:unknown'
    if case=='bad-family':p.requests[0].family_id='family:unknown'
    if case=='repeat-request':p.requests.append(p.requests[0].model_copy())
    if case=='repeat-pair':
        q=p.requests[0].model_copy();q.id='request:duplicate';p.requests.append(q)
    if case=='repeat-person':p.participant_ids.append(p.participant_ids[0])
    if case=='repeat-family':p.families.append(p.families[0].model_copy())
    r=solve_options(p)
    assert r.status=='INVALID_INPUT' and r.witness is None


def test_zero_budget_returns_unknown_without_unproved_infeasibility():
    r=solve_options(triangle(),{'max_time_seconds':0})
    assert r.status=='UNKNOWN' and r.proof_scope=='NONE' and r.witness is None


def test_restrict_large_flexible_mode_explicitly_no_silent_fallback():
    p,_=c0_build()
    r=solve_options(p,{'strategy':'FLEXIBLE_SECTIONS','max_flexible_requests':200,'max_time_seconds':1})
    assert r.status=='UNSUPPORTED' and r.witness is None
    assert 'limit' in r.findings[0].lower()


def test_strict_option_fields_reject_unknown_options():
    assert solve_options(triangle(),{'unknown_property':99}).status=='INVALID_INPUT'


def test_no_auto_global_block_optimality_claim_for_single_family_profile():
    p,_=c0_build()
    r=solve_options(p,{'max_time_seconds':8})
    assert r.status=='FEASIBLE' and r.block_optimality_scope=='SINGLE_BLOCK_ONLY'
    assert r.quality_optimality=='NOT_CLAIMED'


def test_flexible_no_section_minimization_still_returns_valid_assignment():
    p=triangle()
    r=solve_options(p,{'strategy':'FLEXIBLE_SECTIONS','max_time_seconds':7,'minimise_sections':False})
    check_complete(p,r)
    assert not r.min_section_count_proven


def test_incomplete_invalid_problem_shape_fails_closed():
    r=solve_options({'problem_id':'bad','participant_ids':[],'requests':[],'families':[]})
    assert r.status=='INVALID_INPUT' and r.witness is None


def brute_flexible_has_solution(p):
    """Tiny independent enumerator: direct request/block choices, no CP-SAT."""
    from itertools import product
    fam={f.id:f for f in p.families}
    req=p.requests
    for blocks in product(range(p.max_blocks),repeat=len(req)):
        by_learner=set(); counts=Counter(); feasible=True
        for r,b in zip(req,blocks):
            key=(r.participant_id,b)
            if key in by_learner:feasible=False;break
            by_learner.add(key);counts[(r.family_id,b)]+=1
        if not feasible:continue
        for fid,f in fam.items():
            valid_counts=[]
            for b in range(p.max_blocks):
                n=counts[fid,b]
                possible=[k for k in range(f.max_sections+1)
                          if (n==0 and k==0) or (k>0 and k*f.min_members<=n<=k*f.max_members)]
                if not possible:feasible=False;break
                valid_counts.append(min(possible))
            if not feasible or sum(valid_counts)>f.max_sections:feasible=False;break
        if feasible:return True
    return False


def test_small_randomised_flexible_solver_matches_independent_enumerator():
    rng=Random(8125)
    for scenario in range(12):
        people=[f'person:R{n}' for n in range(4)]
        families=[]
        for v in range(3):
            minimum=rng.choice([1,2]);maximum=rng.choice([2,3])
            families.append({'id':f'family:F{v}','label':f'F{v}',
                'min_members':minimum,'max_members':maximum,
                'max_sections':rng.choice([1,2,3])})
        requests=[]
        for p in people:
            selected=rng.sample([f['id'] for f in families],rng.choice([1,2]))
            for f in selected:
                requests.append({'id':f'request:{p}:{f}','participant_id':p,'family_id':f})
        problem=OptionDesignProblem.model_validate({'problem_id':f'random:case{scenario}',
            'model_version':1,'participant_ids':people,'families':families,
            'requests':requests,'max_blocks':2})
        expected=brute_flexible_has_solution(problem)
        result=solve_options(problem,{'strategy':'FLEXIBLE_SECTIONS','max_time_seconds':4})
        assert result.status == ('FEASIBLE' if expected else 'INFEASIBLE'), (scenario,result.findings)
        if expected:check_complete(problem,result)
        else:assert result.proof_scope=='FULL_O1'
