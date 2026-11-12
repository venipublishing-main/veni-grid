"""Explicit Q1 quality penalties; hand-calculated oracle, no optimiser involved."""
from copy import deepcopy
import pytest
from veni_grid_contract.core_v1 import CoreProblem, CoreWitness
from veni_grid_contract.conformance import review_core
from veni_grid_quality import QualityPolicy, compare, digest, score


def examples():
    days = [{'id':f'day:D{i}', 'label':f'Day {i}','ordinal':i} for i in (1,2)]
    windows = []
    for day in (1,2):
        for period in (1,2,3):
            start = 440 + 40*period
            windows.append({'id':f'window:D{day}P{period}', 'day_id':f'day:D{day}',
                'bell_id':'bell:main','sequence':period,'start_minute':start,'end_minute':start+40,
                'tags':['FINAL'] if period==3 else []})
    resources = [
        {'id':'person:student','kind':'PERSON','label':'Synthetic student'},
        {'id':'group:G','kind':'GROUP','label':'Group','member_ids':['person:student']},
        {'id':'person:T','kind':'PERSON','label':'Teacher'},
        {'id':'space:R1','kind':'SPACE','label':'R1','capacity':25,'location_id':'loc:A'},
        {'id':'space:R2','kind':'SPACE','label':'R2','capacity':25,'location_id':'loc:B'},
    ]
    events=[]
    for i in (1,2):
        events.append({'id':f'event:E{i}','label':f'Lesson {i}','activity_id':'activity:M',
            'duration':{'unit':'WINDOWS','count':1},'fixed_participant_ids':['group:G'],
            'placement':{'start_window_ids':[x['id'] for x in windows]},
            'requirements':[{'id':f'req:E{i}:T','kind':'PERSON','role':'TEACHER','quantity':1,
                             'eligible_resource_ids':['person:T']},
                            {'id':f'req:E{i}:R','kind':'SPACE','role':'ROOM','quantity':1,
                             'eligible_resource_ids':['space:R1','space:R2']}]})
    p=CoreProblem.model_validate({'problem_id':'q1:toy','model_version':1,'vertical_id':'TEST',
        'days':days,'windows':windows,'resources':resources,
        'activities':[{'id':'activity:M','label':'Math','demand':{'basis':'GLOBAL','unit':'WINDOWS','amount':2}}],
        'events':events,'locations':[{'id':'loc:A','label':'A'},{'id':'loc:B','label':'B'}]})
    def witness(second_window='window:D1P3', second_room='space:R2'):
        return CoreWitness.model_validate({'solution_id':'solution:q1','problem_id':p.problem_id,
            'model_version':p.model_version,'status':'FEASIBLE','validation':'UNVALIDATED',
            'event_assignments':[
                {'event_id':'event:E1','start_window_id':'window:D1P1','resource_allocations':[
                    {'requirement_id':'req:E1:T','resource_ids':['person:T']},
                    {'requirement_id':'req:E1:R','resource_ids':['space:R1']}]},
                {'event_id':'event:E2','start_window_id':second_window,'resource_allocations':[
                    {'requirement_id':'req:E2:T','resource_ids':['person:T']},
                    {'requirement_id':'req:E2:R','resource_ids':[second_room]}]},
            ]})
    return p,witness


def policy(p, metrics=None):
    return QualityPolicy.model_validate({'id':'policy:Q1','model_sha256':digest(p),'metrics':metrics or [
        {'id':'metric:spread','kind':'ACTIVITY_DAY_PAIRS','tier':2,'weight':10,'activity_ids':['activity:M']},
        {'id':'metric:idle','kind':'RESOURCE_IDLE_MINUTES','tier':3,'weight':1,'resource_ids':['person:T']},
        {'id':'metric:load','kind':'RESOURCE_DAILY_LOAD_SPREAD','tier':3,'weight':1,'resource_ids':['person:T'],'day_ids':['day:D1','day:D2']},
        {'id':'metric:room','kind':'RESOURCE_LOCATION_CHANGES','tier':3,'weight':20,'resource_ids':['person:T']},
        {'id':'metric:late','kind':'TAGGED_PLACEMENTS','tier':4,'weight':4,'event_ids':['event:E1','event:E2'],'tags':['FINAL']},
    ]})


def comp(r):return {x.metric_id:x for x in r.components}


def test_all_independent_base_math():
    p,w=examples(); candidate=w()
    assert review_core(p,candidate).result == 'CANDIDATE_HARD_VALIDATED'
    r=score(p,candidate,policy(p))
    assert r.status=='SCORED' and r.hard_validation=='PASSED'
    assert r.lexicographic_vector==[10,140,4]
    assert comp(r)['metric:spread'].raw_penalty == 1
    assert comp(r)['metric:idle'].raw_penalty == 40
    assert comp(r)['metric:load'].raw_penalty == 80
    assert comp(r)['metric:room'].raw_penalty == 1
    assert comp(r)['metric:late'].raw_penalty == 1
    assert r.quality_optimality=='NOT_ASSESSED' and r.publication=='NOT_GRANTED'


def test_better_neighbour_comparison_is_lexicographic():
    p,w=examples(); pol=policy(p)
    poor=score(p,w(),pol)
    improved=score(p,w('window:D1P2','space:R1'),pol)
    spread=score(p,w('window:D2P1','space:R1'),pol)
    assert improved.lexicographic_vector == [10,80,0]
    assert spread.lexicographic_vector == [0,0,0]
    assert compare(poor,improved).winner=='RIGHT'
    assert compare(spread,improved).winner=='LEFT'
    assert compare(poor,poor).winner=='TIE'


def test_weights_never_override_higher_priority():
    p,w=examples()
    pol=policy(p,[
        {'id':'metric:high','kind':'ACTIVITY_DAY_PAIRS','tier':2,'weight':1,'activity_ids':['activity:M']},
        {'id':'metric:lower','kind':'RESOURCE_DAILY_LOAD_SPREAD','tier':3,'weight':1000000,
         'resource_ids':['person:T'],'day_ids':['day:D1','day:D2']}])
    same_day=score(p,w('window:D1P2'),pol)
    separate_days=score(p,w('window:D2P1'),pol)
    assert same_day.lexicographic_vector==[1,80000000,0]
    assert separate_days.lexicographic_vector==[0,0,0]
    assert compare(same_day,separate_days).winner=='RIGHT'


def test_comparison_requires_same_problem_and_policy():
    p,w=examples(); a=score(p,w(),policy(p))
    p2=p.model_copy(deep=True);p2.model_version=2
    b=score(p2,w(),policy(p2))
    assert b.status=='INVALID_CANDIDATE'
    assert compare(a,b).status=='INCOMPARABLE'
    other=policy(p,metrics=[{'id':'metric:only','kind':'ACTIVITY_DAY_PAIRS','tier':2,'weight':1,'activity_ids':['activity:M']}])
    assert compare(a,score(p,w(),other)).status=='INCOMPARABLE'


def test_invalid_candidate_never_scored():
    p,w=examples();bad=w('window:D1P1')
    r=score(p,bad,policy(p))
    assert r.status=='INVALID_CANDIDATE' and r.hard_validation=='FAILED'
    assert not r.lexicographic_vector


def test_policy_stale_hash_refused_even_if_witness_valid():
    p,w=examples(); pol=policy(p).model_dump(mode='json');pol['model_sha256']='0'*64
    assert score(p,w(),pol).status=='INVALID_INPUT'

@pytest.mark.parametrize('modify',[
    lambda x: x['metrics'][0].update(activity_ids=['activity:unknown']),
    lambda x: x['metrics'][1].update(resource_ids=['space:R1']),
    lambda x: x['metrics'][1].update(resource_ids=['person:unknown']),
    lambda x: x['metrics'][0].update(activity_ids=['activity:M','activity:M']),
    lambda x: x['metrics'][2].update(day_ids=['day:unknown']),
    lambda x: x['metrics'][3].update(kind='TYPO'),
    lambda x: x['metrics'][0].update(weight=0),
    lambda x: x['metrics'][0].update(tier=1),
    lambda x: x.update(extra_field=True),
])
def test_bad_quality_policy_never_silently_ignored(modify):
    p,w=examples();d=policy(p).model_dump(mode='json');modify(d)
    assert score(p,w(),d).status=='INVALID_INPUT'


def test_unresolved_location_fails_closed():
    p,w=examples();p=p.model_copy(deep=True)
    r=next(x for x in p.resources if x.id=='space:R2');r.location_id=None
    report=score(p,w(),policy(p))
    assert report.status=='UNRESOLVED_CONTEXT' and report.hard_validation=='PASSED'
    assert 'location missing' in report.findings[0]


def test_unscored_legacy_objective_is_obvious():
    p,w=examples();p=p.model_copy(deep=True)
    from veni_grid_contract.models import Objective
    p.objectives.append(Objective(id='objective:old',tier=3,metric='GENERAL_RULE_PENALTY',weight=1))
    r=score(p,w(),policy(p))
    assert r.status=='INCOMPLETE_SCORING'
    assert r.unscored_objective_ids==['objective:old']
    assert compare(r,r).status=='INCOMPARABLE'


def test_determinism_and_nonmutation():
    p,w=examples();candidate=w(); pol=policy(p)
    before=(digest(p),digest(candidate),digest(pol))
    a=score(p,candidate,pol)
    b=score(p,candidate,pol)
    assert a.model_dump(mode='json')==b.model_dump(mode='json')
    assert before==(digest(p),digest(candidate),digest(pol))


def test_soft_request_penalty_and_unscored_scope():
    p,w=examples();p=p.model_copy(deep=True)
    from veni_grid_contract.models import Activity, Demand, Event, WindowDuration, PlacementDomain, Offering, ParticipationRequest
    p.activities.append(Activity(id='activity:art',label='Art',demand=Demand(basis='PER_ENROLLED',unit='WINDOWS',amount=1)))
    p.events.append(Event(id='event:art',label='Art',activity_id='activity:art',offering_id='offer:art',required=False,
        duration=WindowDuration(count=1),placement=PlacementDomain(start_window_ids=['window:D2P3'])))
    p.offerings.append(Offering(id='offer:art',activity_id='activity:art',event_ids=['event:art'],capacity=1))
    p.participation_requests.append(ParticipationRequest(id='req:art',participant_id='person:student',activity_id='activity:art',
        eligible_offering_ids=['offer:art'],strength='SOFT',min_select=1,max_select=1))
    from veni_grid_contract.models import EnrollmentAssignment
    base = w()
    base.enrollment_assignments.append(EnrollmentAssignment(request_id="req:art", offering_ids=[]))
    pol=policy(p)
    unscored=score(p,base,pol)
    assert unscored.status=='INCOMPLETE_SCORING' and unscored.unscored_soft_request_ids==['req:art']
    full=QualityPolicy.model_validate({'id':'policy:full','model_sha256':digest(p),'metrics':[
        {'id':'metric:unmet','kind':'UNMET_SOFT_REQUESTS','tier':2,'weight':3,'request_ids':['req:art']}]})
    r=score(p,base,full)
    assert r.status=='SCORED' and r.lexicographic_vector==[3,0,0]
    assert r.components[0].contributions=={'req:art':1}



def test_last_period_tag_does_not_leak_across_bell_schedules():
    p,w=examples()
    p=p.model_copy(deep=True)
    from veni_grid_contract.models import TimeWindow
    # An entirely separate bell regime also overlaps the first event.
    # Its FINAL tag must not make D1P1 a 'last period' placement.
    p.windows.append(TimeWindow(id='window:other',day_id='day:D1',bell_id='bell:alternate',
                                sequence=1,start_minute=480,end_minute=520,tags=['FINAL']))
    pol=policy(p,metrics=[{'id':'metric:tag','kind':'TAGGED_PLACEMENTS','tier':4,'weight':5,
                          'event_ids':['event:E1'],'tags':['FINAL']}])
    result=score(p,w(),pol)
    assert result.status=='SCORED' and result.lexicographic_vector==[0,0,0]


def test_unknown_and_self_claimed_validation_rejected():
    p,w=examples()
    unknown=w(); unknown.status='UNKNOWN'
    assert score(p,unknown,policy(p)).status=='INVALID_CANDIDATE'
    pretend=w(); pretend.validation='PASSED'
    assert score(p,pretend,policy(p)).status=='INVALID_CANDIDATE'


def test_partial_soft_rule_is_not_misrepresented_as_complete():
    p,w=examples();p=p.model_copy(deep=True)
    from veni_grid_contract.models import ActivitySpread
    p.constraints.append(ActivitySpread(id='rule:prefer',source='USER',strength='SOFT',
                                        activity_ids=['activity:M'],minimum_distinct_days=2))
    result=score(p,w(),policy(p))
    assert result.status=='INCOMPLETE_SCORING'
    assert result.unscored_soft_rule_ids==['rule:prefer']
