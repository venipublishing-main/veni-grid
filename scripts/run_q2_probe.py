"""Synthetic C1 vs Q2 Benchmark B quality test. No live data or publication."""
from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
from time import perf_counter
import argparse,json, platform
from scripts.build_benchmark_b import build
from veni_grid_quality.policies import benchmark_b_policy
from veni_grid_quality import score,compare
from veni_grid_quality.optimize import optimise
from veni_grid_solver import solve

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'q2-output'


def run(seconds=12.0):
    OUT.mkdir(exist_ok=True)
    p,known=build()
    pol=benchmark_b_policy(p)
    initial=solve(p)
    if initial.status!='FEASIBLE' or initial.validation!='PASSED':
        raise RuntimeError(f'C1 benchmark B was not independently valid: {initial.status}')
    r=optimise(p,pol,{'max_time_seconds':seconds})
    if r.status!='FEASIBLE' or r.independent_validation!='PASSED' or r.quality is None:
        raise RuntimeError(f'Q2 did not return a validated candidate: {r.status}; {r.findings}')
    qknown=score(p,known,pol)
    qc1=score(p,initial.candidate,pol)
    if any(x.status!='SCORED' for x in [qknown,qc1,r.quality]):
        raise RuntimeError('Scoring incomplete; cannot compare')
    if compare(qknown,r.quality).winner=='LEFT':
        raise RuntimeError('Q2 failed to beat the reference known-valid case on its test policy')
    if compare(qc1,r.quality).winner=='LEFT':
        raise RuntimeError('Q2 failed to beat the original C1-generated case on its test policy')
    if len(r.candidate.event_assignments)!=240:
        raise RuntimeError('Q2 did not schedule all 240 lesson events')
    record={
        'run_time_utc':datetime.now(timezone.utc).isoformat(),
        'platform':platform.platform(),
        'python':platform.python_version(),
        'problem_id':p.problem_id,
        'model_hash':r.model_sha256,
        'policy_hash':r.policy_sha256,
        'events':len(p.events),'students':120,'staff':24,'rooms':12,
        'all_synthetic':True,
        'c1':{'status':initial.status,'independent_validation':initial.validation,
              'quality_vector':qc1.lexicographic_vector,'solve_ms':initial.solve_ms},
        'known_valid':{'quality_vector':qknown.lexicographic_vector},
        'q2':{'status':r.status,'independent_validation':r.independent_validation,
              'quality_optimality':r.quality_optimality,'quality_vector':r.quality.lexicographic_vector,
              'stages':[s.model_dump(mode='json') for s in r.stages],
              'elapsed_ms':r.total_ms,'notes':r.findings},
        'improvement_vs_reference_general_percent':round(100*(qknown.lexicographic_vector[1]-r.quality.lexicographic_vector[1])/qknown.lexicographic_vector[1],2),
        'unmet_requested_features':'Not a full-curriculum school, learner-choice auto grouping, repair, publication or UI solver',
    }
    (OUT/'benchmark-b-q2-result.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    (OUT/'benchmark-b-q2-candidate.json').write_text(r.candidate.model_dump_json(indent=2)+'\n',encoding='utf-8')
    lines=['# Veni Grid Q2 — Benchmark B controlled comparison','','All three schedules independently satisfy the same hard-constraint model.','This policy is synthetic; lower penalties are better and vectors compare lexicographically.','','| Schedule | Critical tier 2 | General tier 3 | Aesthetic tier 4 |','|---|---:|---:|---:|']
    for name,v in [('Known-valid reference',qknown.lexicographic_vector),('C1 feasibility',qc1.lexicographic_vector),('Q2 optimisation',r.quality.lexicographic_vector)]:
        lines.append(f'| {name} | {v[0]} | {v[1]} | {v[2]} |')
    lines.extend(['',f'General quality improved {record["improvement_vs_reference_general_percent"]}% versus the supplied reference under the test policy.','',f'Q2 quality proof status: **{r.quality_optimality}**.',''])
    for s in r.stages:lines.append(f'- Tier {s.tier}: {s.solver_status}, objective {s.objective_value}, proved {s.proven_optimal}')
    lines.extend(['','The C1 problem schema and hard-rule solver were not modified.','No full-school realism or universal runtime claim is implied. No publication was attempted.',''])
    (OUT/'benchmark-b-q2-comparison.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({k:v for k,v in record.items() if k not in ('model_hash','policy_hash')},indent=2))
    return record

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--seconds',type=float,default=12)
    run(ap.parse_args().seconds)
