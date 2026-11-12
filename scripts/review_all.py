"""Run all contract witnesses without a solver, PC, network, or external service."""
from __future__ import annotations
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from veni_grid_contract.models import SchedulingProblem,SchedulingSolution
from veni_grid_contract.validation import witness_issues
from veni_grid_contract.option_design import OptionDesignProblem,OptionDesignWitness,option_errors
from veni_grid_contract.coverage import CoverageProblem,CoverageWitness,coverage_errors,duty_minutes
from veni_grid_contract.calendar_projection import CalendarProjection,project_calendar
from veni_grid_contract.jobs import SchedulingJob,JobProposal,ScheduleVersion,proposal_errors
ROOT=Path(__file__).resolve().parents[1]
def read(folder,name):return json.loads((folder/f'{name}.json').read_text())
def report(case,errors,**facts):
    item={'case':case,'status':'PASS' if not errors else 'FAIL','findings':[str(i) for i in errors],**facts}
    print(json.dumps(item))
    return not errors
okay=True
for case in ['master_school','learner_choices','invigilation']:
    folder=ROOT/'fixtures'/case
    p=SchedulingProblem.model_validate(read(folder,'problem'));w=SchedulingSolution.model_validate(read(folder,'solution-witness'))
    okay=report(case,witness_issues(p,w),assignments=len(w.event_assignments)) and okay
for case in ['F1_shared_capacity']:
    folder=ROOT/'fixtures_v03'/case;p=SchedulingProblem.model_validate(read(folder,'problem'));w=SchedulingSolution.model_validate(read(folder,'witness'))
    okay=report(case,witness_issues(p,w),capacity=100,peak_configured_use=100) and okay
for case in ['F2_option_design','F2b_1500_choice_representation']:
    folder=ROOT/'fixtures_v03'/case;p=OptionDesignProblem.model_validate(read(folder,'problem'));w=OptionDesignWitness.model_validate(read(folder,'witness'))
    okay=report(case,option_errors(p,w),participants=len(p.participant_ids),requests=len(p.requests),sections=len(w.offerings),solver_run=False) and okay
case='F3_segmented_invigilation';folder=ROOT/'fixtures_v03'/case
p=CoverageProblem.model_validate(read(folder,'problem'));w=CoverageWitness.model_validate(read(folder,'witness'))
okay=report(case,coverage_errors(p,w),duty_minutes=duty_minutes(w)) and okay
case='F4_cycle_calendar';folder=ROOT/'fixtures_v03'/case
p=CalendarProjection.model_validate(read(folder,'problem'));out=[x.model_dump(mode='json') for x in project_calendar(p)]
okay=report(case,[] if out==read(folder,'witness')['occurrences'] else ['Projection mismatch'],occurrences=len(out)) and okay
case='J1_linked_scoped_job';folder=ROOT/'fixtures_v03'/case
p=SchedulingJob.model_validate(read(folder,'problem'));w=JobProposal.model_validate(read(folder,'witness'));current=[ScheduleVersion.model_validate(x) for x in read(folder,'current_versions')]
okay=report(case,proposal_errors(p,w,current),writable_schedules=len(p.targets),read_only_schedules=len(p.dependencies)) and okay
raise SystemExit(0 if okay else 1)
