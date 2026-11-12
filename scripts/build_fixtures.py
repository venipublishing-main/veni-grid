"""Generate synthetic cross-vertical contract examples; no real school data."""
from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'fixtures'

def out(case,prob,sol):
    d=BASE/case;d.mkdir(parents=True,exist_ok=True)
    for name,content in [('problem.json',prob),('solution-witness.json',sol)]:
        (d/name).write_text(json.dumps(content,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

def day(i,label,date=None):return {'id':f'day:{i}','label':label,'ordinal':i, 'date':date}
def window(day,seq,start,end,bell='bell:standard',tags=None):
    return dict(id=f'win:{day}:{bell.split(":")[1]}:{seq}',day_id=f'day:{day}',bell_id=bell,sequence=seq,start_minute=start,end_minute=end,tags=tags or [])
def person(pid,label,tags=None,blackouts=None):return dict(id=f'res:person:{pid}',kind='PERSON',label=label,tags=tags or [],unavailable_window_ids=blackouts or [])
def room(pid,label,cap):return dict(id=f'res:room:{pid}',kind='SPACE',label=label,capacity=cap)
def group(pid,label,students):return dict(id=f'res:group:{pid}',kind='GROUP',label=label,member_ids=[f'res:person:{s}' for s in students])
def activity(pid,label,basis,unit,amount,tags=None):return dict(id=f'act:{pid}',label=label,demand={'basis':basis,'unit':unit,'amount':amount},tags=tags or [])
def need(pid,role,kind,resource_ids,amount=1,mincap=None):
    d=dict(id=f'need:{pid}',role=role,kind=kind,quantity=amount,eligible_resource_ids=resource_ids)
    if mincap is not None:d['minimum_capacity']=mincap
    return d
def event(pid,label,aid,duration,starts,needs,fixed=None,offering=None,required=True):
    return dict(id=f'evt:{pid}',label=label,activity_id=f'act:{aid}',offering_id=f'offer:{offering}' if offering else None,required=required,fixed_participant_ids=fixed or [],duration=duration,placement={'start_window_ids':starts},requirements=needs)
def assign(pid,win,reqs):return dict(event_id=f'evt:{pid}',start_window_id=win,resource_allocations=[dict(requirement_id=f'need:{r}',resource_ids=ids) for r,ids in reqs])
def problem(name,vertical,days,windows,resources,activities,events,offerings=None,requests=None,rules=None,locks=None,objectives=None):
    return dict(schema_version='0.3.0-draft',problem_id=f'prob:{name}',model_version=1,vertical_id=vertical,
        timezone='Africa/Johannesburg',days=days,windows=windows,resources=resources,activities=activities,
        events=events,offerings=offerings or [],participation_requests=requests or [],constraints=rules or [],
        objectives=objectives or [],locks=locks or [],solve_config={'mode':'FEASIBILITY','time_limit_seconds':30,'random_seed':1,'deterministic':True})
def sol(name,ea,en=None):return dict(schema_version='0.3.0-draft',solution_id=f'sol:{name}:witness',problem_id=f'prob:{name}',model_version=1,status='FEASIBLE',event_assignments=ea,enrollment_assignments=en or [],validation='UNVALIDATED')
def rule(code,kind,strength='HARD',**extra):return dict(id=f'rule:{code}',kind=kind,strength=strength,source='USER',priority=3,weight=1,enabled=True,**extra)
def w(dayid,seq,bell='standard'):return f'win:{dayid}:{bell}:{seq}'

# Case 1: rotating academic master schedule with joins, shared teachers and double lab lessons.
D=[day(1,'Mon'),day(2,'Tue'),day(3,'Wed'),day(4,'Thu'),day(5,'Fri')]
W=[window(d,s,*times, tags=['instructional']) for d in range(1,6) for s,times in enumerate([(480,530),(535,585),(600,650)],1)]
R=[person(x,x) for x in ['A1','A2','B1','B2','T_MATH','T_SCI','T_ENG']]+[
    group('G7A','7A',['A1','A2']),group('G7B','7B',['B1','B2']),
    room('R101','Classroom 101',30),room('R102','Classroom 102',30),room('LAB','Science Lab',20),room('HALL','Assembly Hall',80)]
A=[activity('MATH_A','7A Mathematics','GLOBAL','WINDOWS',2),activity('MATH_B','7B Mathematics','GLOBAL','WINDOWS',2),
   activity('SCI_A','7A Science double','GLOBAL','WINDOWS',2),activity('SCI_B','7B Science double','GLOBAL','WINDOWS',2),
   activity('ASSEMBLY','Combined grade assembly','GLOBAL','WINDOWS',1),activity('ENG_B','7B English','GLOBAL','WINDOWS',1)]
reqMath=lambda id,roomid:[need(id+':t','INSTRUCTOR','PERSON',['res:person:T_MATH']),need(id+':r','SPACE','SPACE',[f'res:room:{roomid}'])]
reqSci=lambda id:[need(id+':t','INSTRUCTOR','PERSON',['res:person:T_SCI']),need(id+':r','SPACE','SPACE',['res:room:LAB'])]
E=[event('MA1','Math 7A 1','MATH_A',{'unit':'WINDOWS','count':1},[w(1,1)],reqMath('MA1','R101'),['res:group:G7A']),
   event('MA2','Math 7A 2','MATH_A',{'unit':'WINDOWS','count':1},[w(4,1)],reqMath('MA2','R101'),['res:group:G7A']),
   event('MB1','Math 7B 1','MATH_B',{'unit':'WINDOWS','count':1},[w(1,2)],reqMath('MB1','R102'),['res:group:G7B']),
   event('MB2','Math 7B 2','MATH_B',{'unit':'WINDOWS','count':1},[w(5,1)],reqMath('MB2','R102'),['res:group:G7B']),
   event('SA','Science double 7A','SCI_A',{'unit':'WINDOWS','count':2,'max_gap_minutes':5},[w(2,1)],reqSci('SA'),['res:group:G7A']),
   event('SB','Science double 7B','SCI_B',{'unit':'WINDOWS','count':2,'max_gap_minutes':5},[w(3,1)],reqSci('SB'),['res:group:G7B']),
   event('ASM','Combined grade assembly','ASSEMBLY',{'unit':'WINDOWS','count':1},[w(2,3)],
         [need('ASM:t','SUPERVISOR','PERSON',['res:person:T_ENG']),need('ASM:r','SPACE','SPACE',['res:room:HALL'],mincap=4)],['res:group:G7A','res:group:G7B']),
   event('EB1','English 7B','ENG_B',{'unit':'WINDOWS','count':1},[w(1,1)],
         [need('EB1:t','INSTRUCTOR','PERSON',['res:person:T_ENG']),need('EB1:r','SPACE','SPACE',['res:room:R102'])],['res:group:G7B'])]
maRules=[rule('spread_a','ACTIVITY_SPREAD',activity_ids=['act:MATH_A'],minimum_distinct_days=2),
         rule('math_unavail','RESOURCE_BLACKOUT',resource_id='res:person:T_MATH',window_ids=[w(2,3)])]
maLocks=[{'id':'lock:matha1','event_id':'evt:MA1','start_window_id':w(1,1),'source':'USER_LOCK'}]
maProb=problem('master_school','schools.master',D,W,R,A,E,rules=maRules,locks=maLocks)
maS=sol('master_school',[
    assign('MA1',w(1,1),[('MA1:t',['res:person:T_MATH']),('MA1:r',['res:room:R101'])]),
    assign('MA2',w(4,1),[('MA2:t',['res:person:T_MATH']),('MA2:r',['res:room:R101'])]),
    assign('MB1',w(1,2),[('MB1:t',['res:person:T_MATH']),('MB1:r',['res:room:R102'])]),
    assign('MB2',w(5,1),[('MB2:t',['res:person:T_MATH']),('MB2:r',['res:room:R102'])]),
    assign('SA',w(2,1),[('SA:t',['res:person:T_SCI']),('SA:r',['res:room:LAB'])]),
    assign('SB',w(3,1),[('SB:t',['res:person:T_SCI']),('SB:r',['res:room:LAB'])]),
    assign('ASM',w(2,3),[('ASM:t',['res:person:T_ENG']),('ASM:r',['res:room:HALL'])]),
    assign('EB1',w(1,1),[('EB1:t',['res:person:T_ENG']),('EB1:r',['res:room:R102'])])])
out('master_school',maProb,maS)

# Case 2: learner course requests and distinct selectable sections, with alternate bell regime.
D=[day(1,'Cycle Monday'),day(2,'Cycle Tuesday')]
W=[window(d,s,*times,tags=['lesson']) for d in (1,2) for s,times in enumerate([(480,530),(535,585)],1)]
W += [window(d,1,510,560,bell='bell:seminar',tags=['seminar']) for d in (1,2)]
R=[person(s,s) for s in ('S1','S2','S3','TP','TA','TR')]+[room('LAB','Physics laboratory',2),room('RACC','Accounting Room',2),room('RART','Art Studio',2)]
A=[activity('PHYS','Physics course','PER_ENROLLED','WINDOWS',1),activity('ACC','Accounting course','PER_ENROLLED','WINDOWS',1),activity('ART','Art elective','PER_ENROLLED','WINDOWS',1)]
configs=[('PHYA','PHYS',w(1,1),'TP','LAB',2),('PHYB','PHYS',w(1,2),'TP','LAB',1),('PHYC','PHYS',w(2,2),'TP','LAB',1),('PHYD','PHYS',w(2,1),'TP','LAB',2),
         ('ACCA','ACC',w(1,1),'TA','RACC',1),('ACCB','ACC',w(2,1),'TA','RACC',1),('ARTA','ART',w(1,1,'seminar'),'TR','RART',2)]
E=[]; O=[]
for sid,aid,start,staff,space,cap in configs:
    starts=[w(1,1,'seminar'),w(2,1,'seminar')] if sid=='ARTA' else [start]
    E.append(event(sid,sid,aid,{'unit':'WINDOWS','count':1},starts,
        [need(sid+':t','INSTRUCTOR','PERSON',[f'res:person:{staff}']),need(sid+':r','SPACE','SPACE',[f'res:room:{space}'])],offering=sid,required=False))
    O.append({'id':f'offer:{sid}','activity_id':f'act:{aid}','event_ids':[f'evt:{sid}'],'capacity':cap,'activation':'ON_ENROLLMENT'})
def preq(n,student,activity,offers):return dict(id=f'req:{n}',participant_id=f'res:person:{student}',activity_id=f'act:{activity}',eligible_offering_ids=[f'offer:{o}' for o in offers],min_select=1,max_select=1,strength='HARD',priority=2)
P=[preq('S1PHY','S1','PHYS',['PHYA','PHYB','PHYC','PHYD']),preq('S1ACC','S1','ACC',['ACCA','ACCB']),
   preq('S2PHY','S2','PHYS',['PHYA','PHYB','PHYC','PHYD']),preq('S2ACC','S2','ACC',['ACCA','ACCB']),
   preq('S3PHY','S3','PHYS',['PHYA','PHYB','PHYC','PHYD']),preq('S3ART','S3','ART',['ARTA'])]
chProb=problem('learner_choices','schools.options',D,W,R,A,E,offerings=O,requests=P,
    objectives=[{'id':'obj:choice','tier':2,'metric':'UNMET_PARTICIPATION_REQUESTS','weight':100}])
chS=sol('learner_choices',[
  assign(sid,w(1,1,'seminar') if sid=='ARTA' else start,[(sid+':t',[f'res:person:{staff}']),(sid+':r',[f'res:room:{space}'])])
  for sid,aid,start,staff,space,cap in configs if sid in ('PHYA','PHYB','PHYC','ACCA','ACCB','ARTA')],
  [dict(request_id=f'req:{r}',offering_ids=[f'offer:{o}']) for r,o in [('S1PHY','PHYB'),('S1ACC','ACCA'),('S2PHY','PHYA'),('S2ACC','ACCB'),('S3PHY','PHYC'),('S3ART','ARTA')]])
out('learner_choices',chProb,chS)

# Case 3: fixed-dated exam sessions, venue capacity, staff choice and invigilation fairness.
D=[day(1,'Monday',date='2027-11-15'),day(2,'Tuesday',date='2027-11-16')]
W=[window(1,1,510,690,bell='bell:exam',tags=['morning']),
   window(1,2,630,810,bell='bell:exam',tags=['late-morning']),
   window(1,3,780,900,bell='bell:exam',tags=['afternoon']),
   window(2,1,510,690,bell='bell:exam',tags=['morning'])]
R=[person(s,s) for s in ['M1','M2','M3','M4','L1','L2','L3','C1','C2']+['I1','I2','I3','I4']]+[
    group('MATH','Mathematics candidates',['M1','M2','M3','M4']),
    group('LANG','Languages candidates',['L1','L2','L3']),
    group('SCI','Science candidates',['C1','C2']),
    room('HALL','Exam hall',80),room('ROOM','Language room',40),room('LAB','Exam laboratory',30)]
A=[activity('EX_M','Mathematics paper','GLOBAL','MINUTES',150),activity('EX_L','Language paper','GLOBAL','MINUTES',150),
   activity('EX_S','Science paper','GLOBAL','MINUTES',180)]
E=[event('EX_M','Math Paper','EX_M',{'unit':'MINUTES','count':150},[w(1,1,'exam')],
    [need('EX_M:i','INVIGILATOR','PERSON',['res:person:I1','res:person:I2','res:person:I3','res:person:I4'],amount=2),
     need('EX_M:r','SPACE','SPACE',['res:room:HALL'],mincap=4)],['res:group:MATH']),
   event('EX_L','Language Paper','EX_L',{'unit':'MINUTES','count':150},[w(1,2,'exam')],
    [need('EX_L:i','INVIGILATOR','PERSON',['res:person:I1','res:person:I2','res:person:I3','res:person:I4']),
     need('EX_L:r','SPACE','SPACE',['res:room:ROOM'],mincap=3)],['res:group:LANG']),
   event('EX_S','Science Paper','EX_S',{'unit':'MINUTES','count':180},[w(2,1,'exam')],
    [need('EX_S:i','INVIGILATOR','PERSON',['res:person:I1','res:person:I2','res:person:I3','res:person:I4']),
     need('EX_S:r','SPACE','SPACE',['res:room:LAB'],mincap=2)],['res:group:SCI'])]
Rul=[rule('I2_no_pm','RESOURCE_BLACKOUT',resource_id='res:person:I2',window_ids=[w(1,3,'exam')]),
     rule('I4_not_math','EXCLUDE_RESOURCE_FROM_EVENT',event_ids=['evt:EX_M'],resource_ids=['res:person:I4'],role='INVIGILATOR'),
     rule('max_daily','MAX_DAILY_MINUTES',resource_ids=[f'res:person:I{i}' for i in range(1,5)],limit_minutes=180),
     rule('balance','WORKLOAD_BALANCE','SOFT',resource_ids=[f'res:person:I{i}' for i in range(1,5)],metric='ASSIGNMENT_COUNT',target_spread=0)]
L=[{'id':'lock:mathstart','event_id':'evt:EX_M','start_window_id':w(1,1,'exam'),'source':'USER_LOCK'}]
iProb=problem('invigilation','schools.invigilation',D,W,R,A,E,rules=Rul,locks=L,
    objectives=[{'id':'obj:load','tier':3,'metric':'GENERAL_RULE_PENALTY','weight':10}])
iS=sol('invigilation',[
  assign('EX_M',w(1,1,'exam'),[('EX_M:i',['res:person:I1','res:person:I2']),('EX_M:r',['res:room:HALL'])]),
  assign('EX_L',w(1,2,'exam'),[('EX_L:i',['res:person:I3']),('EX_L:r',['res:room:ROOM'])]),
  assign('EX_S',w(2,1,'exam'),[('EX_S:i',['res:person:I4']),('EX_S:r',['res:room:LAB'])])])
out('invigilation',iProb,iS)
print('Generated 3 contract fixtures with independently authored positive witnesses')
