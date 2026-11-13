"""Benchmark C0: 1,500 synthetic learners' demands, not a sectioning solver.

Families are deliberately aligned to candidate block groups for a guaranteed
witness; this is a model/validator load probe, NOT hard option-block discovery.
"""
from __future__ import annotations
from pathlib import Path
from veni_grid_contract.option_design import (
    OptionDesignProblem, OptionDesignWitness, option_errors,
)

ROOT=Path(__file__).resolve().parents[1]


def build():
    people=[f'person:S{i:04d}' for i in range(1500)]
    families=[{'id':f'family:F{b:02d}{v}', 'label':f'Synthetic subject {b+1}.{v+1}',
               'min_members':20,'max_members':25,'max_sections':25}
              for b in range(6) for v in range(3)]
    requests=[]
    for i,person in enumerate(people):
        for b in range(6):
            fid=f'family:F{b:02d}{(i+b)%3}'
            requests.append({'id':f'request:S{i:04d}:B{b}',
                             'participant_id':person,'family_id':fid})
    problem=OptionDesignProblem.model_validate({'problem_id':'benchmark:C0:synthetic',
        'model_version':1,'participant_ids':people,'families':families,
        'requests':requests,'max_blocks':6})
    block_ids=[f'block:B{b}' for b in range(6)]
    offerings=[]
    for b in range(6):
        for v in range(3):
            for section in range(25):
                offerings.append({'id':f'offering:B{b}V{v}S{section:02}',
                                  'family_id':f'family:F{b:02d}{v}',
                                  'block_id':block_ids[b]})
    seen={f'family:F{b:02d}{v}':0 for b in range(6) for v in range(3)}
    allocation=[]
    for req in requests:
        fam=req['family_id'];n=seen[fam];seen[fam]+=1
        b=int(fam[8:10]);v=int(fam[-1]);section=n//20
        allocation.append({'request_id':req['id'],
                           'offering_id':f'offering:B{b}V{v}S{section:02}'})
    witness=OptionDesignWitness.model_validate({'problem_id':problem.problem_id,
        'model_version':1,'block_ids':block_ids,'offerings':offerings,'allocations':allocation})
    errors=option_errors(problem,witness)
    if errors:raise ValueError('C0 witness invalid: '+str(errors[:3]))
    return problem,witness


def main():
    p,w=build(); folder=ROOT/'benchmark-c0-output';folder.mkdir(exist_ok=True)
    (folder/'problem.json').write_text(p.model_dump_json(indent=2)+'\n')
    (folder/'synthetic-witness.json').write_text(w.model_dump_json(indent=2)+'\n')
    print(f'C0 represented and validated: {len(p.participant_ids)} learners, '
          f'{len(p.requests)} requests, {len(p.families)} families, '
          f'{len(w.offerings)} sections, {len(w.block_ids)} option blocks')


if __name__=='__main__':main()
