"""Fresh-checkout verification with logs, strict evidence counts and real CP-SAT.

Writes synthetic development evidence only. Does not deploy, publish timetables,
access a school system, or use an AI/Codex API.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'ci-output'


def run_logged(name: str, args: list[str]) -> str:
    command = [sys.executable, *args]
    process = subprocess.run(command, cwd=ROOT,
                             env=dict(os.environ, PYTHONUTF8='1', PYTHONUNBUFFERED='1'),
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding='utf-8', errors='replace', timeout=600)
    (OUT / f'{name}.txt').write_text(process.stdout, encoding='utf-8')
    print(process.stdout, end='', flush=True)
    if process.returncode:
        raise RuntimeError(f'{name} exited with {process.returncode}; see its log')
    return process.stdout


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    OUT.mkdir(exist_ok=True)
    # Never let a previous success receipt survive a failed verification run.
    summary = {'status': 'RUNNING', 'started_at': datetime.now(timezone.utc).isoformat(),
               'github_sha': os.environ.get('GITHUB_SHA'),
               'pull_request_head_sha': os.environ.get('PR_HEAD_SHA'),
               'run_id': os.environ.get('GITHUB_RUN_ID'),
               'python': platform.python_version(), 'platform': platform.platform()}
    receipt = OUT / 'verification.json'
    receipt.write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    try:
        run_logged('source-import', ['-m', 'scripts.verify_source_import'])
        run_logged('prepare', ['-m', 'scripts.prepare_workspace'])
        run_logged('pytest-output', ['-m', 'pytest', '-q', '--junitxml=ci-output/pytest-results.xml'])
        suites = ET.parse(OUT / 'pytest-results.xml').getroot()
        counts = {key: sum(int(s.attrib.get(key, 0)) for s in suites.iter('testsuite'))
                  for key in ['tests', 'failures', 'errors', 'skipped']}
        require(counts == {'tests': 423, 'failures': 0, 'errors': 0, 'skipped': 0},
                f'Unexpected regression coverage: {counts}')
        text = run_logged('contract-scenarios', ['-m', 'scripts.review_candidate'])
        scenarios = [json.loads(line) for line in text.splitlines() if line.startswith('{')]
        require(len(scenarios) == 18, f'Expected 18 contract scenarios, got {len(scenarios)}')
        require(all(item.get('passed') is True or item.get('result') == 'PASS'
                    or item.get('status') == 'PASS' for item in scenarios), 'A contract scenario failed')
        (OUT / 'contract-scenarios.json').write_text(json.dumps(scenarios, indent=2) + '\n', encoding='utf-8')
        run_logged('solver-benchmarks', ['-m', 'scripts.run_solver_benchmarks'])
        benchmarks = json.loads((ROOT / 'evidence_solver/benchmark-summary.json').read_text(encoding='utf-8'))
        require(len(benchmarks) == 12, f'Expected 12 solver benchmark cases, got {len(benchmarks)}')
        require(all(b['status'] == b['expected'] for b in benchmarks), 'Unexpected solver status')
        require(all(b['independent_validation'] == 'PASSED' for b in benchmarks if b['status'] == 'FEASIBLE'),
                'A generated candidate did not pass independent validation')
        school = next(b for b in benchmarks if b['name'] == 'school-benchmark-a')
        require(school['events'] == 24, 'School benchmark must generate all 24 events')
        zero = next(b for b in benchmarks if b['name'] == 'school-zero-budget')
        require(zero['status'] == 'UNKNOWN' and zero['proven_infeasible'] is False,
                'Zero-budget case must not claim infeasibility')
        run_logged('source-import-after', ['-m', 'scripts.verify_source_import'])
        summary.update(status='PASS', tests=counts, contract_scenarios=len(scenarios),
                       solver_benchmarks=len(benchmarks), benchmark_statuses=dict(Counter(b['status'] for b in benchmarks)),
                       school_events=school['events'], source_files_verified=43,
                       dependencies={name: version(name) for name in ['ortools', 'pydantic', 'jsonschema', 'pytest']},
                       deployment='NOT_PERFORMED', publication='NOT_GRANTED')
    except Exception as exc:
        summary.update(status='FAIL', error=f'{type(exc).__name__}: {exc}')
        print(summary['error'], file=sys.stderr)
    finally:
        summary['finished_at'] = datetime.now(timezone.utc).isoformat()
        receipt.write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, indent=2))
    return 0 if summary['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
