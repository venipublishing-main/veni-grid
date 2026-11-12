"""Usage: python -m veni_grid_solver INPUT.json --output RESULT.json"""
import argparse
import json
import sys
from pathlib import Path
from .runtime import solve, SolverOptions

def main():
    parser=argparse.ArgumentParser(description='Veni Grid C1 hard-feasibility solver (not publishing)')
    parser.add_argument('input',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--time-limit',type=float)
    args=parser.parse_args()
    try:
        data=json.loads(args.input.read_text(encoding='utf-8'))
        result=solve(data,SolverOptions(max_time_seconds=args.time_limit))
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(result.model_dump_json(indent=2)+'\n',encoding='utf-8')
    except (OSError,ValueError) as exc:
        parser.exit(2,f'Input/output error: {exc}\n')
    print(f'{result.status} | CP-SAT={result.solver_status} | independent validation={result.validation}')
    if result.status=='FEASIBLE':return 0
    if result.status=='INFEASIBLE':return 3
    if result.status=='UNKNOWN':return 4
    return 2

if __name__=='__main__':sys.exit(main())
