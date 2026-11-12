from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import json
import pytest
from veni_grid_contract.core_v1 import CoreProblem, CoreWitness, core_witness_errors
from veni_grid_contract.conformance import review_core
from veni_grid_solver import solve, SolverOptions
from veni_grid_solver.compiler import HARD_RULES, Compiler, placements
from .helpers import base, raw, rule, pin, rule_case

ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('kind',sorted(HARD_RULES))
@pytest.mark.parametrize('feasible',[True,False])
def test_every_hard_rule_positive_and_negative(kind,feasible):
    p=rule_case(kind,feasible)
    r=solve(p)
    assert r.status==('FEASIBLE' if feasible else 'INFEASIBLE'),r.model_dump_json(indent=2)
    assert r.proven_infeasible is (not feasible)
    if feasible:
        assert r.validation=='PASSED' and not core_witness_errors(p,r.candidate)
    else:assert r.solver_status=='INFEASIBLE' and r.candidate is None

@pytest.mark.parametrize('path',[
 'fixtures/master_school/problem.json','fixtures/learner_choices/problem.json','fixtures/invigilation/problem.json',
 'fixtures_v03/F1_shared_capacity/problem.json','fixtures_rc/R1_operational/problem.json',
 'fixtures_v04/H1_options_to_lessons/handoff.json','fixtures_rc/R3_flexible_options/handoff.json'])
def test_inherited_inputs_generate_without_loading_witnesses(path):
    p=json.loads((ROOT/path).read_text())
    if 'problem' in p:p=p['problem']
    p['schema_version']='1.0.0-rc1'
    r=solve(p)
    assert r.status=='FEASIBLE',r.findings
    assert r.validation=='PASSED'
    assert review_core(CoreProblem.model_validate(p),r.candidate).result=='CANDIDATE_HARD_VALIDATED'

def test_solver_never_calls_witness_checker_to_search(monkeypatch):
    # The only call to review_core belongs after search, never while enumerating.
    import veni_grid_solver.runtime as rt
    real=rt.review_core; calls=[]
    def spy(p,w):calls.append(w);return real(p,w)
    monkeypatch.setattr(rt,'review_core',spy)
    r=solve(base());assert r.status=='FEASIBLE' and len(calls)==1

def test_input_immutability_and_repeatability():
    p=base();before=p.model_dump_json()
    a=solve(p);b=solve(p)
    assert before==p.model_dump_json()
    assert a.candidate==b.candidate
    assert a.compiled_model_hash==b.compiled_model_hash

def test_real_zero_search_budget_unknown_not_infeasible():
    r=solve(base(),SolverOptions(max_time_seconds=0))
    assert r.status=='UNKNOWN' and r.solver_status=='UNKNOWN'
    assert not r.proven_infeasible and r.candidate is None

def test_real_zero_deterministic_budget_unknown():
    r=solve(base(),{'max_deterministic_time':0})
    assert r.status=='UNKNOWN' and r.solver_status=='UNKNOWN'

@pytest.mark.parametrize('mode',['OPTIMISE','REPAIR','DIAGNOSE','COMPARE'])
def test_unsupported_operation_refused(mode):
    p=raw(base());p['solve_config']['mode']=mode
    r=solve(p);assert r.status=='UNSUPPORTED' and r.solver_status=='NOT_RUN'

def test_baseline_not_silently_ignored():
    p=raw(base());p['baseline_solution_id']='solution:baseline'
    assert solve(p).status=='UNSUPPORTED'

def test_deterministic_workers_gate():
    assert solve(base(),{'workers':2}).status=='UNSUPPORTED'

def test_unknown_rules_and_bad_references_are_input_errors():
    p=raw(base());p['constraints']=[rule('UNKNOWN_RULE')]
    assert solve(p).status=='INVALID_INPUT'
    p=raw(base());p['events'][0]['activity_id']='activity:missing'
    assert solve(p).status=='INVALID_INPUT'

def test_invalid_compiled_model_is_runtime_error(monkeypatch):
    real=Compiler.compile
    def broken(self):
        obj=real(self);obj.m.new_int_var(5,1,'bad-domain');return obj
    monkeypatch.setattr(Compiler,'compile',broken)
    r=solve(base())
    assert r.status=='ERROR' and r.solver_status=='MODEL_INVALID'
    assert any(f.code=='COMPILED_MODEL_INVALID' for f in r.findings)

def test_independent_checker_withholds_corrupt_extraction(monkeypatch):
    real=Compiler.extract
    def broken(self,engine,digest):
        w=real(self,engine,digest);w.event_assignments[0].start_window_id='win:missing';return w
    monkeypatch.setattr(Compiler,'extract',broken)
    r=solve(base())
    assert r.status=='ERROR' and r.validation=='FAILED' and r.candidate is None

def test_quality_optimality_is_never_claimed():
    r=solve(base())
    assert r.status=='FEASIBLE' and r.solver_status in ('FEASIBLE','OPTIMAL')
    assert r.quality_optimality=='NOT_ASSESSED' and r.publish_permission=='NOT_GRANTED'

def test_soft_preferences_listed_but_not_hard_constraints():
    p=raw(rule_case('RESOURCE_BLACKOUT',False));p['constraints'][0]['strength']='SOFT'
    r=solve(p)
    assert r.status=='FEASIBLE' and r.ignored_soft_rule_ids==['rule:test']
    assert r.soft_scoring=='NOT_PERFORMED'

def test_disabled_rule_not_compiled():
    p=raw(rule_case('RESOURCE_BLACKOUT',False));p['constraints'][0]['enabled']=False
    assert solve(p).status=='FEASIBLE'

def test_double_cannot_cross_break_or_day_end():
    p=raw(base(1));p['activities'][0]['demand']['amount']=2;p['events'][0]['duration']['count']=2
    r=solve(p);assert r.status=='INFEASIBLE' # every adjacent period has a 15m gap
    p['events'][0]['duration']['max_gap_minutes']=15
    r=solve(p);assert r.status=='FEASIBLE'

def test_work_minutes_exclude_allowed_break():
    p=raw(base(1));p['activities'][0]['demand']['amount']=2
    p['events'][0]['duration']={'unit':'WINDOWS','count':2,'max_gap_minutes':15}
    p['events'][0]['requirements'][0]['eligible_resource_ids']=['teacher:A']
    p['constraints']=[rule('MAX_DAILY_MINUTES',resource_ids=['teacher:A'],limit_minutes=60)]
    assert solve(p).status=='FEASIBLE'
    p['constraints'][0]['limit_minutes']=59
    assert solve(p).status=='INFEASIBLE'

def test_actual_interval_overlap_across_bell_ids():
    p=raw(base());p['windows'].append({'id':'win:alt','day_id':'day:D1','bell_id':'bell:alt','sequence':1,'start_minute':500,'end_minute':530})
    pin(p,0,'win:D1P1','teacher:A');pin(p,1,'win:alt','teacher:A')
    assert solve(p).status=='INFEASIBLE'

def test_room_capacity_counts_unique_known_learners():
    p=raw(base(1));p['resources'].append({'id':'pupil:extra','kind':'PERSON','label':'Extra'})
    p['events'][0]['fixed_participant_ids'].append('pupil:extra')
    for r in p['resources']:
        if r['kind']=='SPACE':r['capacity']=1
    assert solve(p).status=='INFEASIBLE'

def test_same_resource_cannot_fill_two_explicit_roles():
    p=raw(base(1));q=deepcopy(p['events'][0]['requirements'][0]);q['id']='req:second';q['eligible_resource_ids']=['teacher:A']
    p['events'][0]['requirements'][0]['eligible_resource_ids']=['teacher:A'];p['events'][0]['requirements'].append(q)
    assert solve(p).status=='INFEASIBLE'

def test_nested_group_overlap():
    p=raw(base());p['resources'] += [{'id':'group:inner','kind':'GROUP','label':'inner','member_ids':['pupil:P0']},
                                   {'id':'group:outer','kind':'GROUP','label':'outer','member_ids':['group:inner']}]
    p['events'][0]['fixed_participant_ids']=['group:outer'];p['events'][1]['fixed_participant_ids']=['pupil:P0']
    pin(p,0,'win:D1P1','teacher:A','room:R0');pin(p,1,'win:D1P1','teacher:B','room:R1')
    assert solve(p).status=='INFEASIBLE'

def test_lock_start_and_allocation_respected():
    p=raw(base());p['locks']=[{'id':'lock:first','event_id':'event:E0','start_window_id':'win:D2P2',
                            'requirement_id':'req:T0','resource_ids':['teacher:B']}]
    r=solve(p);assert r.status=='FEASIBLE'
    e=next(a for a in r.candidate.event_assignments if a.event_id=='event:E0')
    assert e.start_window_id=='win:D2P2'
    assert next(a.resource_ids for a in e.resource_allocations if a.requirement_id=='req:T0')==['teacher:B']

def test_contradictory_valid_locks_are_infeasible_not_bad_input():
    p=raw(base());p['locks']=[{'id':'lock:one','event_id':'event:E0','start_window_id':'win:D1P1'},
                           {'id':'lock:two','event_id':'event:E0','start_window_id':'win:D2P1'}]
    assert solve(p).status=='INFEASIBLE'

def test_minute_event_cannot_exceed_start_session():
    p=raw(base(1));p['activities'][0]['demand']={'basis':'GLOBAL','unit':'MINUTES','amount':31}
    p['events'][0]['duration']={'unit':'MINUTES','count':31}
    assert solve(p).status=='INFEASIBLE'

@pytest.mark.parametrize('capacity,expected',[(100,'FEASIBLE'),(99,'INFEASIBLE')])
def test_shared_venue_total_capacity(capacity,expected):
    p=json.loads((ROOT/'fixtures_v03/F1_shared_capacity/problem.json').read_text());p['schema_version']='1.0.0-rc1'
    for r in p['resources']:
        if r.get('sharing_mode')=='CUMULATIVE':r['capacity']=capacity
    assert solve(p).status==expected

def test_missing_consumption_is_refusal_not_infeasibility():
    p=json.loads((ROOT/'fixtures_v03/F1_shared_capacity/problem.json').read_text());p['schema_version']='1.0.0-rc1'
    for q in p['events'][0]['requirements']:q['usage_units']=None
    r=solve(p);assert r.status=='UNSUPPORTED' and not r.proven_infeasible

def test_dated_qualification_covers_end_not_only_start():
    p=raw(rule_case('QUALIFICATION',True));pin(p,0,'win:D1P1','teacher:A')
    p['days'][0]['date']='2027-02-01';p['days'][1]['date']='2027-02-02'
    p['credentials'][0]['valid_during']={'start':'2027-02-01T08:00:00+02:00','end':'2027-02-01T08:29:00+02:00'}
    assert solve(p).status=='INFEASIBLE'
    p['credentials'][0]['valid_during']['end']='2027-02-01T08:30:00+02:00'
    assert solve(p).status=='FEASIBLE'

def test_cyclic_dated_credentials_refuse_without_fabricating_impossibility():
    p=raw(rule_case('QUALIFICATION',True));p['credentials'][0]['valid_during']={'start':'2027-01-01T00:00:00+02:00','end':'2027-12-31T23:59:00+02:00'}
    r=solve(p);assert r.status=='UNSUPPORTED' and any(f.code=='QUALIFICATION_NEEDS_DATES' for f in r.findings)

def test_missing_route_refuses_not_zero():
    p=raw(rule_case('TRAVEL_TIME',True));p['travel_arcs']=p['travel_arcs'][:1]
    r=solve(p);assert r.status=='UNSUPPORTED' and not r.proven_infeasible

@pytest.mark.parametrize('minutes,expected',[(14,'FEASIBLE'),(15,'FEASIBLE'),(16,'INFEASIBLE')])
def test_travel_threshold(minutes,expected):
    p=raw(rule_case('TRAVEL_TIME',True));p['travel_arcs'][0]['minutes']=minutes
    assert solve(p).status==expected

def test_reverse_route_is_not_assumed_symmetric():
    p=raw(rule_case('TRAVEL_TIME',True));pin(p,0,'win:D1P1','teacher:A','room:R1');pin(p,1,'win:D1P2','teacher:A','room:R0')
    assert solve(p).status=='INFEASIBLE' # reverse needs 25 not 15

def test_travel_uses_only_actual_consecutive_events():
    p=raw(base(3));p['resources'].append({'id':'room:R2','kind':'SPACE','label':'R2','capacity':30,'location_id':'loc:C'})
    p['locations']=[{'id':f'loc:{s}','label':s} for s in 'ABC']
    for r in p['resources']:
        if r['id']=='room:R0':r['location_id']='loc:A'
        if r['id']=='room:R1':r['location_id']='loc:B'
    p['windows'].append({'id':'win:D1P3','day_id':'day:D1','bell_id':'bell:main','sequence':3,'start_minute':570,'end_minute':600})
    for i in range(3):
        pin(p,i,f'win:D1P{i+1}','teacher:A')
        p['events'][i]['requirements'][1]['eligible_resource_ids']=[f'room:R{i}']
    p['travel_arcs']=[{'from_location':f'loc:{a}','to_location':f'loc:{b}','minutes':100 if (a,b)==('A','C') else 10}
                      for a in 'ABC' for b in 'ABC' if a!=b]
    p['constraints']=[rule('TRAVEL_TIME',resource_ids=['teacher:A'])]
    # A->C direct needs 100; A->B->C are the actual adjacent journeys and feasible.
    assert solve(p).status=='FEASIBLE'

def test_continuity_compares_co_teaching_sets_not_order():
    p=raw(base());
    for e in p['events']:e['requirements'][0]['quantity']=2
    p['events'][1]['requirements'][0]['eligible_resource_ids'].reverse()
    p['constraints']=[rule('RESOURCE_CONTINUITY',allocations=[{'event_id':'event:E0','requirement_id':'req:T0'},{'event_id':'event:E1','requirement_id':'req:T1'}])]
    assert solve(p).status=='FEASIBLE'

def test_cross_day_elapsed_gap():
    p=raw(base());pin(p,0,'win:D1P2');pin(p,1,'win:D2P1')
    p['constraints']=[rule('EVENT_BEFORE',earlier_event_id='event:E0',later_event_id='event:E1',minimum_gap_minutes=1366)]
    assert solve(p).status=='INFEASIBLE' # day1 09:15 -> day2 08:00 =1365m
    p['constraints'][0]['minimum_gap_minutes']=1365
    assert solve(p).status=='FEASIBLE'

def test_utc_elapsed_gap_across_dst():
    p=raw(base());p['timezone']='Europe/London'
    p['days'][0]['date']='2027-03-27';p['days'][1]['date']='2027-03-28'
    pin(p,0,'win:D1P1');pin(p,1,'win:D2P1')
    p['constraints']=[rule('EVENT_BEFORE',earlier_event_id='event:E0',later_event_id='event:E1',minimum_gap_minutes=1380)]
    assert solve(p).status=='INFEASIBLE' # 22h30 actual gap, not 23h30

def test_schema_stays_rc1():
    p=base();r=solve(p)
    assert r.candidate.schema_version==p.schema_version=='1.0.0-rc1'

@pytest.mark.parametrize('explicit_rule',[False,True])
def test_nested_group_availability_regression(explicit_rule):
    original=json.loads((ROOT/'evidence_solver/validator-regression-before.json').read_text())
    p=original['input'];w=CoreWitness.model_validate(original['candidate'])
    if explicit_rule:
        next(r for r in p['resources'] if r['id']=='group:inner')['unavailable_window_ids']=[]
        p['constraints']=[rule('RESOURCE_BLACKOUT',resource_id='group:inner',window_ids=['win:D1P1'])]
    p=CoreProblem.model_validate(p)
    assert core_witness_errors(p,w)
    assert solve(p).status=='INFEASIBLE'

@pytest.mark.parametrize('name,expected',[
 ('school-benchmark-a','FEASIBLE'),('school-teacher-shortage','INFEASIBLE'),
 ('school-double-bottleneck','INFEASIBLE'),('school-locked-clash','INFEASIBLE')])
def test_full_school_search_benchmarks(name,expected):
    p=json.loads((ROOT/'fixtures_solver'/f'{name}.json').read_text())
    r=solve(p);assert r.status==expected,r.findings
    if expected=='FEASIBLE':assert len(r.candidate.event_assignments)==24 and r.validation=='PASSED'


def test_cli_emits_result(tmp_path):
    import subprocess,sys
    path=tmp_path/'input.json';out=tmp_path/'result.json';path.write_text(base().model_dump_json())
    completed=subprocess.run([sys.executable,'-m','veni_grid_solver',str(path),'--output',str(out)],text=True,capture_output=True)
    assert completed.returncode==0,completed.stderr
    assert json.loads(out.read_text())['validation']=='PASSED'


def test_unchanged_rc1_input_schema():
    # The checker correction changes no fields, enums or JSON schema structure.
    import jsonschema
    schema=json.loads((ROOT/'schemas/core-problem-rc1.schema.json').read_text())
    jsonschema.validate(base().model_dump(mode='json'),schema)
    assert CoreProblem.model_json_schema()=={k:v for k,v in schema.items() if k not in ('$schema','$id')}

@pytest.mark.parametrize('bad',[True,'1',1.5])
def test_strict_canonical_integer_boundary(bad):
    p=raw(base());p['events'][0]['duration']['count']=bad
    r=solve(p);assert r.status=='INVALID_INPUT' and r.solver_status=='NOT_RUN'


def test_unknown_joint_job_envelope_not_silently_dropped():
    p=raw(base());p['scheduling_job']={'mode':'JOINT','targets':['other:schedule']}
    assert solve(p).status=='INVALID_INPUT'


def test_full_soft_objective_audit():
    p=raw(base());p['objectives']=[{'id':'objective:quality','tier':3,'metric':'GENERAL_RULE_PENALTY','weight':1}]
    r=solve(p);assert r.status=='FEASIBLE' and r.ignored_objective_ids==['objective:quality']
