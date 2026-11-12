"""Synthetic first-school search benchmark; no known solution is supplied to CP-SAT."""
from pathlib import Path
from copy import deepcopy
import json
from veni_grid_contract.core_v1 import CoreProblem

ROOT=Path(__file__).resolve().parents[1]

def build_school():
    days=[{'id':f'day:D{d}','ordinal':d,'label':label} for d,label in enumerate(['Monday','Tuesday','Wednesday','Thursday','Friday'],1)]
    starts=[480,520,560,620,660,700]
    windows=[{'id':f'win:D{d}P{k}','day_id':f'day:D{d}','bell_id':'bell:school','sequence':k,
              'start_minute':s,'end_minute':s+40} for d in range(1,6) for k,s in enumerate(starts,1)]
    resources=[]
    for group in ['G7A','G7B']:
        pupils=[f'person:{group}:L{i:02}' for i in range(1,13)]
        resources += [{'id':pid,'kind':'PERSON','label':f'Synthetic {pid}'} for pid in pupils]
        resources.append({'id':f'group:{group}','kind':'GROUP','label':group,'member_ids':pupils})
    for code in ['MATH','ENG','SCI','LIFE']:
        r={'id':f'teacher:{code}','kind':'PERSON','label':f'T_{code}'}
        if code=='LIFE':r['unavailable_window_ids']=[w['id'] for w in windows if w['day_id']=='day:D1']
        resources.append(r)
    resources += [{'id':f'room:{code}','kind':'SPACE','label':code,'capacity':30} for code in ['R101','R102','LAB1']]
    activities=[];events=[];rules=[]
    for group in ['G7A','G7B']:
        for subject,pattern in [('MATH',[1,1,1,1]),('ENG',[1,1,1,1]),('SCI',[2,1]),('LIFE',[1,1])]:
            aid=f'activity:{group}:{subject}'
            activities.append({'id':aid,'label':f'{group} {subject}','demand':{'basis':'GLOBAL','unit':'WINDOWS','amount':sum(pattern)}})
            for i,count in enumerate(pattern,1):
                eid=f'event:{group}:{subject}:{i:02}'
                events.append({'id':eid,'label':f'{group} {subject} {i}','activity_id':aid,
                               'duration':{'unit':'WINDOWS','count':count},'fixed_participant_ids':[f'group:{group}'],
                               'placement':{'start_window_ids':[w['id'] for w in windows]},
                               'requirements':[{'id':f'req:{group}:{subject}:{i}:teacher','role':'TEACHER','kind':'PERSON','quantity':1,'eligible_resource_ids':[f'teacher:{subject}']},
                                               {'id':f'req:{group}:{subject}:{i}:room','role':'ROOM','kind':'SPACE','quantity':1,
                                                'eligible_resource_ids':['room:LAB1'] if subject=='SCI' else ['room:R101','room:R102'],'minimum_capacity':12}]})
            if subject in ['MATH','ENG']:
                rules.append({'id':f'rule:{group}:{subject}:spread','kind':'ACTIVITY_SPREAD','strength':'HARD','source':'USER',
                              'activity_ids':[aid],'minimum_distinct_days':4})
    p=CoreProblem.model_validate({'problem_id':'schedule:benchmarkA','model_version':1,'vertical_id':'SCHOOLS',
                                 'days':days,'windows':windows,'resources':resources,'activities':activities,'events':events,'constraints':rules})
    return p

def main():
    root=ROOT/'fixtures_solver';root.mkdir(exist_ok=True)
    p=build_school().model_dump(mode='json')
    (root/'school-benchmark-a.json').write_text(json.dumps(p,indent=2)+'\n')
    short=deepcopy(p);short['problem_id']='schedule:benchmarkA-short-teacher'
    usable={'win:D1P1','win:D1P2','win:D2P1','win:D2P2','win:D3P1'}
    for r in short['resources']:
        if r['id']=='teacher:SCI':r['unavailable_window_ids']=[w['id'] for w in p['windows'] if w['id'] not in usable]
    (root/'school-teacher-shortage.json').write_text(json.dumps(short,indent=2)+'\n')
    doubles=deepcopy(p);doubles['problem_id']='schedule:benchmarkA-double-bottleneck'
    usable={'win:D1P1','win:D1P2','win:D2P1','win:D3P1','win:D4P1','win:D5P1'}
    for r in doubles['resources']:
        if r['id']=='room:LAB1':r['unavailable_window_ids']=[w['id'] for w in p['windows'] if w['id'] not in usable]
    (root/'school-double-bottleneck.json').write_text(json.dumps(doubles,indent=2)+'\n')
    clashes=deepcopy(p);clashes['problem_id']='schedule:benchmarkA-locked-clash'
    clashes['locks']=[{'id':f'lock:{g}:math','event_id':f'event:{g}:MATH:01','start_window_id':'win:D1P1'} for g in ['G7A','G7B']]
    (root/'school-locked-clash.json').write_text(json.dumps(clashes,indent=2)+'\n')

if __name__=='__main__':main()
