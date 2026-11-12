"""Recreate disposable synthetic fixtures and schemas from tracked source.

Run only in a development clone: this overwrites the generated fixture folders,
never real school data or a live timetable. No network or solver is used here.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    from veni_grid_contract.models import SchedulingProblem, SchedulingSolution
    schema_dir = ROOT / 'schemas'
    schema_dir.mkdir(exist_ok=True)
    for name, model in [('scheduling-problem', SchedulingProblem),
                        ('scheduling-solution', SchedulingSolution)]:
        schema = model.model_json_schema()
        schema['$schema'] = 'https://json-schema.org/draft/2020-12/schema'
        (schema_dir / f'{name}.schema.json').write_text(
            json.dumps(schema, indent=2) + '\n', encoding='utf-8')
    env = dict(os.environ, PYTHONUTF8='1')
    for module in ['build_fixtures', 'build_v03_fixtures',
                   'export_handoff_schemas', 'build_handoff_fixtures',
                   'export_rc_schemas', 'build_rc_fixtures', 'build_solver_fixtures']:
        subprocess.run([sys.executable, '-m', f'scripts.{module}'],
                       cwd=ROOT, env=env, check=True)
    print('Synthetic fixtures and schemas ready; no timetable search performed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
