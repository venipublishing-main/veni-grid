"""Author synthetic input/witness pairs. Witness construction is NOT optimisation."""
from pathlib import Path
import json, sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from veni_grid_contract.models import SchedulingProblem, SchedulingSolution
from veni_grid_contract.jobs import SchedulingJob, JobProposal
from veni_grid_contract.option_design import OptionDesignProblem, OptionDesignWitness
from veni_grid_contract.coverage import CoverageProblem, CoverageWitness
from veni_grid_contract.calendar_projection import CalendarProjection, project_calendar

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'fixtures_v03'
V='0.3.0-draft'
def save(case,name,data):
    path=OUT/case/f'{name}.json';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,indent=2)+'\n')
def interval(start,end,day='2027-01-11'):
    return {'start':f'{day}T{start}:00+02:00','end':f'{day}T{end}:00+02:00'}
def version(sid,revision=1): return {'schedule_id':sid,'revision':revision,'content_sha256':f'{revision:064x}'}

# F1: the SAME SchedulingProblem dialect as the three pre-existing scenarios.
p={'schema_version':V,'problem_id':'problem:shared','model_version':1,'vertical_id':'exams',
   'days':[{'id':'day:one','label':'Synthetic exam day','ordinal':0,'date':'2027-01-11'}],
   'windows':[{'id':'window:A','day_id':'day:one','bell_id':'bell:exam','sequence':1,'start_minute':540,'end_minute':660},
              {'id':'window:B','day_id':'day:one','bell_id':'bell:exam','sequence':2,'start_minute':600,'end_minute':780}],
   'resources':[{'id':'room:hall','kind':'SPACE','label':'100-seat shared hall','capacity':100,'sharing_mode':'CUMULATIVE'},
                {'id':'group:A','kind':'GROUP','label':'Synthetic group A'}, {'id':'group:B','kind':'GROUP','label':'Synthetic group B'},
                {'id':'staff:A','kind':'PERSON','label':'Synthetic staff A'}, {'id':'staff:B','kind':'PERSON','label':'Synthetic staff B'}],
   'activities':[],'events':[]}
s={'schema_version':V,'solution_id':'solution:shared','problem_id':p['problem_id'],'model_version':1,'status':'FEASIBLE','event_assignments':[]}
for letter,units in [('A',60),('B',40)]:
    p['activities'].append({'id':f'activity:{letter}','label':'Paper '+letter,'demand':{'basis':'GLOBAL','unit':'MINUTES','amount':120}})
    p['events'].append({'id':f'event:{letter}','label':'Paper '+letter,'activity_id':f'activity:{letter}',
        'fixed_participant_ids':[f'group:{letter}'],'duration':{'unit':'MINUTES','count':120},'placement':{'start_window_ids':[f'window:{letter}']},
        'requirements':[{'id':f'requirement:room:{letter}','role':'venue','kind':'SPACE','quantity':1,'eligible_resource_ids':['room:hall'],'minimum_capacity':units,'usage_units':units},
                        {'id':f'requirement:staff:{letter}','role':'supervisor','kind':'PERSON','quantity':1,'eligible_resource_ids':['staff:A','staff:B']}]})
    s['event_assignments'].append({'event_id':f'event:{letter}','start_window_id':f'window:{letter}','resource_allocations':[
        {'requirement_id':f'requirement:room:{letter}','resource_ids':['room:hall']},
        {'requirement_id':f'requirement:staff:{letter}','resource_ids':[f'staff:{letter}']}]})
save('F1_shared_capacity','problem',p);save('F1_shared_capacity','witness',s)

# F2: input contains only requests/family bounds, not section IDs or predefined blocks.
def options(n,capacity):
    p={'schema_version':V,'problem_id':f'problem:options:{n}','model_version':1,
       'participant_ids':[f'learner:{i:04d}' for i in range(n)],'max_blocks':2,
       'families':[{'id':f'family:{subject}','label':subject,'min_members':1,'max_members':capacity,'max_sections':n} for subject in ['Physics','Accounting','Art']], 'requests':[]}
    w={'schema_version':V,'problem_id':p['problem_id'],'model_version':1,'block_ids':['block:one','block:two'],'offerings':[],'allocations':[]}
    buckets={}
    pairs=[('Physics','Accounting'),('Physics','Art'),('Accounting','Art')]
    for i,person in enumerate(p['participant_ids']):
        for j,subject in enumerate(pairs[i%3]):
            rid=f'request:{i:04d}:{subject}';fid=f'family:{subject}';bid=w['block_ids'][j]
            p['requests'].append({'id':rid,'participant_id':person,'family_id':fid})
            buckets.setdefault((fid,bid),[]).append(rid)
    # Construct a hand-designed grouping witness to test the output contract only.
    for (fid,bid),requests in buckets.items():
        for chunk_start in range(0,len(requests),capacity):
            oid=f'section:{len(w["offerings"])+1:04d}'
            w['offerings'].append({'id':oid,'family_id':fid,'block_id':bid})
            w['allocations'] += [{'request_id':rid,'offering_id':oid} for rid in requests[chunk_start:chunk_start+capacity]]
    return p,w
for n,cap,name in [(6,4,'F2_option_design'),(1500,25,'F2b_1500_choice_representation')]:
    p,w=options(n,cap);save(name,'problem',p);save(name,'witness',w)

# F3: exams are fixed facts; staff assignments are the only variable entities.
resources=[{'id':f'staff:I{i}','kind':'PERSON'} for i in range(1,5)]+[{'id':f'room:{x}','kind':'SPACE'} for x in ['A','B']]
resources[0]['unavailable']=[interval('10:15','13:00')]
p={'schema_version':V,'problem_id':'problem:coverage','model_version':1,'schedule_id':'schedule:invigilation','resources':resources,
   'sessions':[{'id':'exam:A','venue_id':'room:A','interval':interval('09:00','12:45')},
               {'id':'exam:B','venue_id':'room:B','interval':interval('09:00','12:00')}],
   'demands':[{'id':'coverage:A:main','session_id':'exam:A','role':'INVIGILATOR','interval':interval('09:00','12:00'),'minimum_staff':2,'eligible_staff_ids':['staff:I1','staff:I2','staff:I3']},
              {'id':'coverage:A:extra','session_id':'exam:A','role':'INVIGILATOR','interval':interval('12:00','12:45'),'minimum_staff':1,'eligible_staff_ids':['staff:I2','staff:I3']},
              {'id':'coverage:B:main','session_id':'exam:B','role':'INVIGILATOR','interval':interval('09:00','12:00'),'minimum_staff':1,'eligible_staff_ids':['staff:I2','staff:I4']}]}
w={'schema_version':V,'problem_id':p['problem_id'],'model_version':1,'duties':[]}
for i,(staff,exam,start,end) in enumerate([('I1','A','09:00','10:15'),('I2','A','09:00','12:45'),('I3','A','10:15','12:00'),('I4','B','09:00','12:00')]):
    w['duties'].append({'id':f'duty:{i+1}','session_id':f'exam:{exam}','resource_id':f'staff:{staff}','role':'INVIGILATOR','interval':interval(start,end)})
save('F3_segmented_invigilation','problem',p);save('F3_segmented_invigilation','witness',w)

# F4: synthetic closure, NOT a claimed public holiday. Cycle freezes on that date.
p={'schema_version':V,'problem_id':'problem:calendar','timezone':'Africa/Johannesburg','anchor_date':'2027-01-11','anchor_cycle_day':1,'cycle_length':10,
   'weekdays':[0,1,2,3,4],'horizon_start':'2027-01-11','horizon_end':'2027-01-27','default_bell_id':'bells:normal',
   'bell_sets':[{'id':'bells:normal','periods':[{'key':'period:one','start_minute':480,'end_minute':525}]},
                {'id':'bells:late','periods':[{'key':'period:one','start_minute':510,'end_minute':555}]}],
   'patterns':[{'id':f'pattern:{group}:{d}','event_id':f'lesson:{group}:{d}','cycle_day':d,'period_key':'period:one'} for group in ['A','B'] for d in range(1,11)],
   'exceptions':[{'date':'2027-01-13','kind':'CLOSED','advance_cycle':False,'reason':'Synthetic training closure, not a public holiday'},
                 {'date':'2027-01-14','kind':'REPLACE_BELLS','advance_cycle':True,'reason':'Synthetic late opening','replacement_bell_id':'bells:late'}],
   'cancellations':[{'pattern_id':'pattern:A:6','date':'2027-01-19','reason':'Fixed examination replaces only this occurrence','authorised_by':'synthetic:planner'}]}
save('F4_cycle_calendar','problem',p)
projected=project_calendar(CalendarProjection.model_validate(p))
save('F4_cycle_calendar','witness',{'occurrences':[o.model_dump(mode='json') for o in projected]})

# Scope: job can change only staffing on one duty; exam date/room remain read-only.
job={'schema_version':V,'job_id':'job:invigilation:repair','purpose':'Replace one invigilator only',
     'mode':'RESPECT_EXISTING','targets':[version('schedule:invigilation')],
     'mutable':[{'schedule_id':'schedule:invigilation','entity_ids':['duty:one'],'fields':['RESOURCES']}],
     'horizon':interval('08:00','13:00'),
     'dependencies':[{'source':version('schedule:exams',7),'claims':[{'id':'claim:exam:hall','schedule_id':'schedule:exams','entity_id':'exam:one','resource_id':'room:hall','interval':interval('09:00','12:00')}]},
                     {'source':version('schedule:lessons',3),'claims':[{'id':'claim:lesson:staff','schedule_id':'schedule:lessons','entity_id':'lesson:one','resource_id':'staff:busy','interval':interval('09:00','10:00')}]}],
     'resources':[{'id':'room:hall','kind':'SPACE'},{'id':'staff:busy','kind':'PERSON'},{'id':'staff:free','kind':'PERSON'}]}
proposal={'schema_version':V,'job_id':job['job_id'],'target_versions':job['targets'],
          'dependency_versions':[d['source'] for d in job['dependencies']],
          'changes':[{'schedule_id':'schedule:invigilation','entity_id':'duty:one','field':'RESOURCES','before':['staff:busy'],'after':['staff:free']}],
          'claims':[{'id':'claim:new:duty','schedule_id':'schedule:invigilation','entity_id':'duty:one','resource_id':'staff:free','interval':interval('09:00','12:00')}]}
save('J1_linked_scoped_job','problem',job);save('J1_linked_scoped_job','witness',proposal)
save('J1_linked_scoped_job','current_versions',job['targets']+[d['source'] for d in job['dependencies']])

for name,cls in [('scheduling-job',SchedulingJob),('job-proposal',JobProposal),('option-design-problem',OptionDesignProblem),('option-design-witness',OptionDesignWitness),
                 ('coverage-problem',CoverageProblem),('coverage-witness',CoverageWitness),('calendar-projection',CalendarProjection)]:
    schema=cls.model_json_schema();schema['$schema']='https://json-schema.org/draft/2020-12/schema'
    (ROOT/'schemas'/f'{name}.schema.json').write_text(json.dumps(schema,indent=2)+'\n')
print('Wrote F1, F2, F2b (1500 learners), F3, F4 and J1 fixtures + component schemas.')
