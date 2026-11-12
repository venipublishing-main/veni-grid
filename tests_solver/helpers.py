from __future__ import annotations
from copy import deepcopy
from veni_grid_contract.core_v1 import CoreProblem


def base(n=2):
    rs=[{'id':r,'kind':'PERSON','label':r} for r in ['teacher:A','teacher:B']+[f'pupil:P{i}' for i in range(n)]]
    rs += [{'id':f'room:R{i}','kind':'SPACE','label':f'Room {i}','capacity':30} for i in range(2)]
    days=[{'id':f'day:D{i}','ordinal':i,'label':f'Day {i}'} for i in (1,2)]
    windows=[{'id':f'win:D{d}P{k}','day_id':f'day:D{d}','bell_id':'bell:main','sequence':k,
              'start_minute':480+(k-1)*45,'end_minute':510+(k-1)*45} for d in (1,2) for k in (1,2)]
    activities=[];events=[]
    for i in range(n):
        activities.append({'id':f'activity:A{i}','label':f'Activity {i}','demand':{'basis':'GLOBAL','unit':'WINDOWS','amount':1}})
        events.append({'id':f'event:E{i}','label':f'Event {i}','activity_id':f'activity:A{i}',
                       'fixed_participant_ids':[f'pupil:P{i}'],'duration':{'unit':'WINDOWS','count':1},
                       'placement':{'start_window_ids':[w['id'] for w in windows]},
                       'requirements':[{'id':f'req:T{i}','role':'TEACHER','kind':'PERSON','quantity':1,
                                        'eligible_resource_ids':['teacher:A','teacher:B']},
                                       {'id':f'req:R{i}','role':'ROOM','kind':'SPACE','quantity':1,
                                        'eligible_resource_ids':['room:R0','room:R1'],'minimum_capacity':1}]})
    return CoreProblem.model_validate({'problem_id':'schedule:test','model_version':1,'vertical_id':'SYNTHETIC',
            'days':days,'windows':windows,'resources':rs,'activities':activities,'events':events})


def raw(p):return p.model_dump(mode='json')

def rule(kind, **kwargs):
    return {'id':'rule:test','kind':kind,'strength':'HARD','source':'USER',**kwargs}

def pin(p, i, win, teacher=None, room=None):
    e=p['events'][i]; e['placement']['start_window_ids']=[win]
    if teacher:e['requirements'][0]['eligible_resource_ids']=[teacher]
    if room:e['requirements'][1]['eligible_resource_ids']=[room]


def rule_case(kind, feasible=True):
    p=raw(base())
    if kind=='RESOURCE_BLACKOUT':
        for i in range(2):p['events'][i]['requirements'][0]['eligible_resource_ids']=['teacher:A']
        p['constraints']=[rule(kind,resource_id='teacher:A',window_ids=['win:D1P1'] if feasible else [w['id'] for w in p['windows']])]
    elif kind=='EXCLUDE_RESOURCE_FROM_EVENT':
        p['constraints']=[rule(kind,event_ids=['event:E0'],resource_ids=['teacher:A'] if feasible else ['teacher:A','teacher:B'],role='TEACHER')]
    elif kind=='MAX_DAILY_MINUTES':
        pin(p,0,'win:D1P1','teacher:A');pin(p,1,'win:D1P2','teacher:A')
        p['constraints']=[rule(kind,resource_ids=['teacher:A'],limit_minutes=60 if feasible else 59)]
    elif kind=='WORKLOAD_BALANCE':
        for e in p['events']:e['requirements'][0]['eligible_resource_ids']=['teacher:A']
        p['constraints']=[rule(kind,resource_ids=['teacher:A','teacher:B'],metric='ASSIGNMENT_COUNT',target_spread=2 if feasible else 1)]
    elif kind=='ACTIVITY_SPREAD':
        p['activities']=p['activities'][:1];p['activities'][0]['demand']['amount']=2
        p['events'][1]['activity_id']='activity:A0'
        if not feasible:
            for e in p['events']:e['placement']['start_window_ids']=['win:D1P1','win:D1P2']
        p['constraints']=[rule(kind,activity_ids=['activity:A0'],minimum_distinct_days=2)]
    elif kind=='EVENT_BEFORE':
        pin(p,0,'win:D1P1','teacher:A');pin(p,1,'win:D1P2','teacher:B')
        p['constraints']=[rule(kind,earlier_event_id='event:E0',later_event_id='event:E1',minimum_gap_minutes=15 if feasible else 16)]
    elif kind=='EVENT_NOT_SAME_TIME':
        pin(p,0,'win:D1P1','teacher:A','room:R0');pin(p,1,'win:D1P2' if feasible else 'win:D1P1','teacher:B','room:R1')
        p['constraints']=[rule(kind,event_ids=['event:E0','event:E1'])]
    elif kind=='EVENT_SAME_START':
        pin(p,0,'win:D1P1','teacher:A','room:R0');pin(p,1,'win:D1P1' if feasible else 'win:D1P2','teacher:B','room:R1')
        p['constraints']=[rule(kind,event_ids=['event:E0','event:E1'])]
    elif kind=='QUALIFICATION':
        p['credentials']=[{'id':'credential:A','resource_id':'teacher:A','competency':'skill:maths','source_ref':'SYNTHETIC'}] if feasible else []
        p['constraints']=[rule(kind,allocations=[{'event_id':'event:E0','requirement_id':'req:T0'}],all_of=['skill:maths'])]
    elif kind=='RESOURCE_CONTINUITY':
        p['events'][0]['requirements'][0]['eligible_resource_ids']=['teacher:A']
        p['events'][1]['requirements'][0]['eligible_resource_ids']=['teacher:A' if feasible else 'teacher:B']
        p['constraints']=[rule(kind,allocations=[{'event_id':'event:E0','requirement_id':'req:T0'},{'event_id':'event:E1','requirement_id':'req:T1'}])]
    elif kind=='TRAVEL_TIME':
        p['locations']=[{'id':'loc:W','label':'West'},{'id':'loc:E','label':'East'}]
        for r in p['resources']:
            if r['id']=='room:R0':r['location_id']='loc:W'
            if r['id']=='room:R1':r['location_id']='loc:E'
        p['travel_arcs']=[{'from_location':'loc:W','to_location':'loc:E','minutes':15 if feasible else 16},
                          {'from_location':'loc:E','to_location':'loc:W','minutes':25}]
        pin(p,0,'win:D1P1','teacher:A','room:R0');pin(p,1,'win:D1P2','teacher:A','room:R1')
        p['constraints']=[rule(kind,resource_ids=['teacher:A'])]
    else:raise ValueError(kind)
    return CoreProblem.model_validate(p)
