"""Reproducible O1 generation: contract-only learner sections, not lesson placement."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime,timezone
import json,platform
from scripts.build_benchmark_c0 import build as build_c0
from scripts.build_benchmark_c1 import build as build_c1
from veni_grid_options import solve_options
from veni_grid_contract.option_design import option_errors

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'o1-output'


def run():
    OUT.mkdir(exist_ok=True)
    p0,old=build_c0()
    c0=solve_options(p0,{'strategy':'AUTO','max_time_seconds':15})
    if c0.status!='FEASIBLE' or c0.independent_validation!='PASSED' or c0.allocations!=9000 or c0.offering_count!=360 or c0.block_count!=6:
        raise RuntimeError('C0 generated result not complete or unexpectedly changed')
    if option_errors(p0,c0.witness):raise RuntimeError('Independent C0 check failed')
    (OUT/'c0-generated-options.json').write_text(c0.witness.model_dump_json(indent=2)+'\n')
    (OUT/'c0-requests-only.json').write_text(p0.model_dump_json(indent=2)+'\n')
    p1=build_c1(repeats=4)
    single=solve_options(p1,{'strategy':'SINGLE_FAMILY_BLOCK','max_time_seconds':5})
    flexible=solve_options(p1,{'strategy':'AUTO','max_time_seconds':12})
    if single.status!='INFEASIBLE' or single.proof_scope!='SINGLE_BLOCK_ONLY':
        raise RuntimeError('Expected a restricted graph impossibility, not general O1 impossibility')
    if flexible.status!='FEASIBLE' or flexible.profile!='FLEXIBLE_SECTIONS' or flexible.independent_validation!='PASSED' or flexible.block_count!=3:
        raise RuntimeError('C1 crossed-subject flexible generation failed')
    if option_errors(p1,flexible.witness):raise RuntimeError('Independent C1 check failed')
    (OUT/'c1-crossed-requests-only.json').write_text(p1.model_dump_json(indent=2)+'\n')
    (OUT/'c1-generated-options.json').write_text(flexible.witness.model_dump_json(indent=2)+'\n')
    from o1_tests.test_o1_solver import triangle
    impossible=solve_options(triangle(sections=1,maximum=2,minimum=2),{'strategy':'AUTO','max_time_seconds':8})
    if impossible.status!='INFEASIBLE' or impossible.proof_scope!='FULL_O1':
        raise RuntimeError('True full-profile infeasibility not proved')
    report={'run_at_utc':datetime.now(timezone.utc).isoformat(),'python':platform.python_version(),
      'platform':platform.platform(),'synthetic_only':True,
      'c0':{k:v for k,v in c0.model_dump(mode='json').items() if k!='witness'},
      'c0_supplied_witness_sections':len(old.offerings),
      'c1_single':{k:v for k,v in single.model_dump(mode='json').items() if k!='witness'},
      'c1_flexible':{k:v for k,v in flexible.model_dump(mode='json').items() if k!='witness'},
      'c1_impossible':{k:v for k,v in impossible.model_dump(mode='json').items() if k!='witness'},
      'teacher_and_rooms':'NOT_MODELLED','academic_lesson_placement':'NOT_MODELLED',
      'automatic_section_construction':'YES','client_publication':'NOT_GRANTED',
      'parity_with_vendors':'NOT_CLAIMED'}
    (OUT/'o1-benchmark-summary.json').write_text(json.dumps(report,indent=2)+'\n')
    lines=['# O1 real choice-construction evidence','','Both cases have **no pre-created blocks or sections in the input**.','',
     '| Test | Requests | Blocks generated | Sections generated | Status |','|---|---:|---:|---:|---|',
     f'| C0 1,500 synthetic learners | 9,000 | {c0.block_count} | {c0.offering_count} | {c0.status}, independently valid |',
     f'| C1 crossing choices | {len(p1.requests)} | {flexible.block_count} | {flexible.offering_count} | {flexible.status}, independently valid |',
     '',f'C1 restricted one-family-block result: **{single.status}** in **{single.proof_scope}** only.',
     f'C1 constrained multi-block impossible variant: **{impossible.status}**, proof scope **{impossible.proof_scope}**.',
     '','No teacher/room/lesson feasibility and no full-school parity are implied. No timetable was published.','']
    (OUT/'o1-benchmark-summary.md').write_text('\n'.join(lines))
    print(json.dumps({k:v for k,v in report.items() if k!='platform'},indent=2))
    return report

if __name__=='__main__':run()
