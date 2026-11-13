"""Q3 versioned quality policy probe; no private datasets or publication."""
from __future__ import annotations
import argparse,json,platform
from pathlib import Path
from time import perf_counter
from datetime import datetime,timezone
from scripts.build_benchmark_b import build
from veni_grid_quality import digest
from veni_grid_quality.models import ActivityPairs,TaggedPlacement
from veni_grid_quality.q3_policy import QualityPolicyV2, ProtectedIdle,TargetLoadDeviation
from veni_grid_quality.q3_score import score_v2,compare_v2
from veni_grid_quality.q3_optimize import optimise_v2
from veni_grid_solver import solve
ROOT=Path(__file__).resolve().parents[1]

def policy_for_b(p):
    staff=sorted(r.id for r in p.resources if r.id.startswith(('person:MATH','person:ENG','person:SCI','person:HIST','person:LIFE')))
    parttimers=sorted(r.id for r in p.resources if r.id.startswith('person:LIFE'))
    return QualityPolicyV2(id='policy:Q3:benchmark-B',model_sha256=digest(p),metrics=[
        ActivityPairs(id='metric:subject-day-pairs',tier=2,weight=5,activity_ids=[a.id for a in p.activities]),
        ProtectedIdle(id='metric:staff-unprotected-gaps',tier=3,weight=1,resource_ids=staff,
            protected_breaks=[{'resource_id':rid,'day_id':day.id,'start_minute':600,'end_minute':620}
                              for rid in staff for day in p.days]),
        TargetLoadDeviation(id='metric:parttime-load-targets',tier=3,weight=1,
            targets=[{'resource_id':rid,'day_id':day.id,'target_minutes':40 if day.ordinal<=2 else 0}
                     for rid in parttimers for day in p.days]),
        TaggedPlacement(id='metric:late',tier=4,weight=10,
             event_ids=[e.id for e in p.events],tags=['FINAL']),
    ])

def run(seconds=12):
    p,known=build();pol=policy_for_b(p)
    a=score_v2(p,known,pol)
    c1=solve(p);b=score_v2(p,c1.candidate,pol) if c1.candidate else None
    t0=perf_counter();q3=optimise_v2(p,pol,{'max_time_seconds':seconds});elapsed=round(perf_counter()-t0,3)
    if a.status!='SCORED' or not b or b.status!='SCORED':
        raise RuntimeError('Synthetic C1 reference incomplete')
    if q3.status!='FEASIBLE' or not q3.quality or q3.quality.status!='SCORED':
        raise RuntimeError(f'Q3 failed to return validated candidate: {q3.status} {q3.findings}')
    if len(q3.candidate.event_assignments)!=240 or q3.independent_validation!='PASSED':
        raise RuntimeError('Q3 candidate failed independent validation or event count')
    # Q3 may be interrupted before improving the reference; never make an invalid superiority claim.
    report={'run_utc':datetime.now(timezone.utc).isoformat(),'python':platform.python_version(),
       'platform':platform.platform(),'problem':p.problem_id,'synthetic':True,
       'people':120,'teachers':24,'events':240,'model_sha256':digest(p),'policy_sha256':digest(pol),
       'known_valid':a.lexicographic_vector,'c1_generated':b.lexicographic_vector,
       'q3_generated':q3.quality.lexicographic_vector,'q3_status':q3.status,
       'q3_optimality':q3.quality_optimality,'q3_stages':[s.model_dump(mode='json') for s in q3.stages],
       'q3_seconds':elapsed,'independent_validation':q3.independent_validation,
       'known_vs_q3':compare_v2(a,q3.quality).model_dump(mode='json'),
       'c1_vs_q3':compare_v2(b,q3.quality).model_dump(mode='json'),
       'not_claimed':['actual school scale','real elective construction','universal policy','production publication']}
    out=ROOT/'q3-output';out.mkdir(exist_ok=True)
    (out/'benchmark-b-q3-result.json').write_text(json.dumps(report,indent=2)+'\n')
    (out/'benchmark-b-q3-policy.json').write_text(pol.model_dump_json(indent=2)+'\n')
    (out/'benchmark-b-q3-candidate.json').write_text(q3.candidate.model_dump_json(indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('model_sha256','policy_sha256')},indent=2))
    return report

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--seconds',type=float,default=12)
    run(ap.parse_args().seconds)
