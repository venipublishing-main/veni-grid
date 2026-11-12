"""Run schema + semantic/witness checks on all three examples."""
from pathlib import Path
import json
from jsonschema import Draft202012Validator
from veni_grid_contract.models import SchedulingProblem,SchedulingSolution
from veni_grid_contract.validation import problem_issues,witness_issues

ROOT=Path(__file__).resolve().parents[1]
prob_schema=json.loads((ROOT/'schemas/scheduling-problem.schema.json').read_text())
sol_schema=json.loads((ROOT/'schemas/scheduling-solution.schema.json').read_text())
for folder in sorted((ROOT/'fixtures').iterdir()):
    if not folder.is_dir():continue
    pd=json.loads((folder/'problem.json').read_text())
    sd=json.loads((folder/'solution-witness.json').read_text())
    Draft202012Validator(prob_schema).validate(pd)
    Draft202012Validator(sol_schema).validate(sd)
    p=SchedulingProblem.model_validate(pd)
    s=SchedulingSolution.model_validate(sd)
    i1=problem_issues(p)
    i2=witness_issues(p,s)
    print(f'{folder.name}: {len(p.events)} events, {len(p.participation_requests)} participant requests, {len(s.event_assignments)} assignments; structural={len(i1)} witness={len(i2)}')
    for issue in i1+i2:print('  '+str(issue))
    assert not i1+i2
