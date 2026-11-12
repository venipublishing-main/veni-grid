# Repository import and verification

## Reviewed input

Source archive: `veni-grid-c1-solver-v0.1.0.zip`.

SHA-256: `daaaeb214428bfeb84b77b6811c3c276ff2aab2e800148c079acd6f13666142b`.

All 42 original Python package/test/generator/review files and the one saved validator-regression JSON are listed in `source-provenance.json`. CI compares their bytes before and after execution. This protects this initial transfer; intentional future code changes need an explicitly reviewed manifest update and new release provenance, not disabling the check.

New repository additions: bootstrap, import verification and CI scripts; pyproject/dependency configuration; workflow; ignore/line-ending rules; public-facing documentation. Private working-document links, raw historical machine logs and binary dependencies are excluded. The original delivery archive is unchanged.

## Reproduction

From an activated Python 3.13 environment:

```bash
python -m pip install -c requirements-solver-reviewed.txt -e ".[solver,test]"
python -m scripts.run_ci
```

The dependency file pins the reviewed direct dependencies. It is not a fully hashed transitive lockfile. Actual execution versions are included in the verification receipt. CI also runs `pip check`.

The workflow uses a read-only contents permission, does not persist checkout credentials, pins its three third-party actions to inspected full commit SHAs, and uses `pull_request` rather than a privileged target-context workflow. It contains no deployment, secrets, publish or auto-merge steps. The original `c1-runtime.yml` smoke workflow is retained unchanged on the initial review branch; it must not be confused with `c1-tests.yml` full conformance.

## Evidence gates

1. Exact source transfer: 43 files match the reviewed SHA-256 manifest.
2. A fresh workspace regenerates all synthetic JSON fixtures and schemas from tracked definitions.
3. Pytest: exactly 423 tests, zero failures/errors/skips.
4. Contract review: 18 successful scenario records. These are supplied-witness checks, not searches.
5. Solver benchmarks: 12 genuine CP-SAT runs; eight feasible, three infeasible, one unknown.
6. Every feasible benchmark passes independent validation; the school case has 24 generated events.
7. Zero-budget search never asserts infeasibility.
8. Recheck source identity after all execution.

CI saves JUnit, text logs, `verification.json`, full benchmark inputs/results and a readable synthetic school grid. Artifacts are retained for seven days; the repository source can regenerate them. No successful CI result grants production publication permission.

## Review boundary

The full-source pull request is intended for review. It does not merge itself, modify the previous `main` baseline, or deploy a service. A green check establishes reproducibility of this bounded prototype, not operational security certification, full-school performance or competitor parity.
