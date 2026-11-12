"""Verify exact imported source bytes against the reviewed delivery.

This verifies transfer identity, not software security or author authentication.
Future intentional source changes require a reviewed provenance update.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    manifest = json.loads((ROOT / 'source-provenance.json').read_text(encoding='utf-8'))
    errors = []
    for relative, expected in manifest['files'].items():
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            errors.append(f'{relative}: missing or invalid path')
        elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            errors.append(f'{relative}: content does not match reviewed source')
    for error in errors:
        print(error)
    print(f'Reviewed import: {len(manifest["files"])} files, {len(errors)} mismatches.')
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
