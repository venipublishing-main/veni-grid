"""Rebuild Benchmark B and compare known vs actually solved timetables.

The two candidates are measured, NOT quality-optimised. A better score is not
an optimality proof and the source has no protected school data.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json
from time import perf_counter
from scripts.build_benchmark_b import build, main as export_fixture
from veni_grid_quality.policies import benchmark_b_policy as b_policy
from veni_grid_quality import score, compare
from veni_grid_solver import solve

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'quality-output'


def run():
    OUT.mkdir(exist_ok=True)
    export_fixture()
    p,known=build()
    policy=b_policy(p)
    a=score(p,known,policy)
    inferior=known.model_copy(deep=True)
    next(x for x in inferior.event_assignments if x.event_id=='event:G00:MATH:D01').start_window_id='window:D01P7'
    inferior_score=score(p,inferior,policy)
    if inferior_score.status!='SCORED' or compare(a,inferior_score).winner!='LEFT':
        raise RuntimeError('Q1 policy did not distinguish the deliberately less convenient hard-valid timetable')
    start=perf_counter()
    actual=solve(p)
    elapsed=round(perf_counter()-start,3)
    if actual.status!='FEASIBLE' or actual.validation!='PASSED':
        raise RuntimeError(f'Benchmark B generation not independently valid: {actual.status}, {actual.findings}')
    b=score(p,actual.candidate,policy)
    if a.status!='SCORED' or b.status!='SCORED':
        raise RuntimeError(f'Q1 quality scoring incomplete: {a.status}, {b.status}')
    result={'benchmark':'B','scenario':'synthetic ten-day school, curriculum subset',
            'timestamp':datetime.now(timezone.utc).isoformat(),
            'events':len(p.events),'resources':len(p.resources),'windows':len(p.windows),
            'students':sum(1 for r in p.resources if r.id.startswith('person:P')),
            'rules':len(p.constraints),'teacher_count':24,
            'solver_status':actual.status,'solver_backend_status':actual.solver_status,
            'independent_validation':actual.validation,'generated_event_count':len(actual.candidate.event_assignments),
            'runtime_seconds_this_environment':elapsed,'model_hash':a.model_sha256,
            'policy_hash':a.policy_sha256,
            'known_witness':a.model_dump(mode='json'),'generated_candidate':b.model_dump(mode='json'),
            'comparison':compare(a,b).model_dump(mode='json'),
            'deliberately_inferior_witness':inferior_score.model_dump(mode='json'),
            'quality_discrimination':compare(a,inferior_score).model_dump(mode='json'),
            'scope':'C1 hard feasibility and external Q1 scoring, not 1,500-learner parity or quality optimisation',
            'deployment':'NOT_PERFORMED','publication':'NOT_GRANTED'}
    (OUT/'benchmark-b-quality.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    (OUT/'benchmark-b-generated-candidate.json').write_text(actual.candidate.model_dump_json(indent=2)+'\n',encoding='utf-8')
    (OUT/'benchmark-b-quality-policy.json').write_text(policy.model_dump_json(indent=2)+'\n',encoding='utf-8')
    lines=['# Veni Grid Q1 — Benchmark B comparison','',
           'These numbers are test-policy penalties, NOT universal quality or optimality scores.','',
           '| Metric | Known-valid | Feasibility solver |','|---|---:|---:|']
    ca={c.metric_id:c for c in a.components}; cb={c.metric_id:c for c in b.components}
    for m in policy.metrics:
        lines.append(f'| {m.kind} | {ca[m.id].weighted_penalty} | {cb[m.id].weighted_penalty} |')
    lines.extend(['',f'Lexicographic vectors: {a.lexicographic_vector} vs {b.lexicographic_vector}.',
                  f'Comparison: {result["comparison"]["winner"]}.',
                  'Both candidates satisfy the hard rules; quality optimisation was NOT performed.',''])
    (OUT/'benchmark-b-scorecard.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('known_witness','generated_candidate','deliberately_inferior_witness')},indent=2))
    return result

if __name__=='__main__':run()
