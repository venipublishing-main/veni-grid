"""Run retained reviews and RC1 positive checks; never run a solver or modify inputs."""
from pathlib import Path
import json, sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from veni_grid_contract.core_v1 import CoreProblem,CoreWitness,core_witness_errors
from veni_grid_contract.recurring_claims import RecurrenceConfig,project_claims
from veni_grid_contract.flexible_options import FlexibleOptionsRequest,build_flexible_handoff,flexible_handoff_errors
from veni_grid_contract.conformance import review_core
from scripts.build_rc_fixtures import flexible_witness
ROOT=Path(__file__).resolve().parents[1]
def load(cls,path):return cls.model_validate_json((ROOT/path).read_text())
def report(name,ok,**values):
    print(json.dumps(dict(scenario=name,result='PASS' if ok else 'FAIL',**values)))
    if not ok:raise SystemExit(1)

if __name__=='__main__':
    import subprocess
    for script in ['review_all.py','review_handoffs.py']:
        subprocess.run([sys.executable,str(ROOT/'scripts'/script)],check=True,cwd=ROOT)
    p=load(CoreProblem,'fixtures_rc/R1_operational/problem.json');w=load(CoreWitness,'fixtures_rc/R1_operational/witness.json')
    r=review_core(p,w);report('RC1-operational',r.result=='CANDIDATE_HARD_VALIDATED',checked_events=len(w.event_assignments),solver=r.solver_execution)
    c=load(RecurrenceConfig,'fixtures_rc/R2_recurring/config.json');out=project_claims(p,w,c)
    report('RC1-recurring',len(out.occurrences)==4 and len(out.claims)==20,occurrences=len(out.occurrences),claims=len(out.claims))
    req=load(FlexibleOptionsRequest,'fixtures_rc/R3_flexible_options/request.json');h=build_flexible_handoff(req)
    report('RC1-flexible-handoff',not flexible_handoff_errors(h),events=len(h.problem.events),requests=len(h.problem.participation_requests))
    cw=flexible_witness(h);report('RC1-flexible-placement',not core_witness_errors(h.problem,cw),generated_by='CONSTRUCTED_WITNESS_NOT_SOLVER')
