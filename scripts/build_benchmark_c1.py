"""C1: crossing learner choices deliberately defeat one-block-per-family keys.

No option blocks or sections appear in the input. Subject requests are invented.
Teacher qualifications, teacher availability, rooms and lesson times are not
part of this O1 option-design benchmark; those require a separate handoff gate.
"""
from __future__ import annotations
from pathlib import Path
from veni_grid_contract.option_design import OptionDesignProblem

ROOT=Path(__file__).resolve().parents[1]

def build(repeats: int=4) -> OptionDesignProblem:
    """Four three-of-four choice signatures, `repeats` learners each.

    Single-block-per-family requires four colours (K4 conflicts); with only
    three blocks, a flexible multi-block section allocation is required.
    """
    if repeats<4:raise ValueError('At least four copies per choice portfolio are needed')
    families=[{'id':f'family:{x}','label':f'Invented {x}',
        'min_members':1,'max_members':6,'max_sections':repeats*3} for x in ('A','B','C','D')]
    people=[];requests=[]
    for omitted in 'ABCD':
        for number in range(repeats):
            pid=f'person:C1{omitted}{number:03d}'
            people.append(pid)
            for family in 'ABCD':
                if family==omitted:continue
                requests.append({'id':f'request:{omitted}{number:03d}:{family}',
                                 'participant_id':pid,'family_id':f'family:{family}'})
    return OptionDesignProblem.model_validate({'problem_id':f'benchmark:C1:{repeats}',
        'model_version':1,'participant_ids':people,'families':families,
        'requests':requests,'max_blocks':3})


def main():
    p=build()
    folder=ROOT/'o1-output';folder.mkdir(exist_ok=True)
    (folder/'benchmark-c1-input.json').write_text(p.model_dump_json(indent=2)+'\n')
    print(f'C1 request-only fixture: {len(p.participant_ids)} learners; {len(p.requests)} choices; 0 prepared sections')

if __name__=='__main__': main()
