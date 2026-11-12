# Veni Grid development boundaries

Preserve independent, on-demand timetables. Shared infrastructure or linked data must never imply permission to change all schedules.

This baseline implements C1 hard feasibility only. Keep contract validation, solver generation, soft scoring, repair and publication distinct. Never silently ignore an unsupported hard rule or turn UNKNOWN into INFEASIBLE. Never return a candidate that fails independent validation.

Before changing code, read README.md, docs/ARCHITECTURE.md and docs/REPOSITORY_VERIFICATION.md. Run `python -m scripts.run_ci`. The initial source-provenance check intentionally freezes the imported release bytes: intentional source changes require a reviewed provenance/version update, not deletion of the guard or weakening tests.

Only synthetic data belongs in this public repository. Do not commit real staff/learner records, private Drive URLs, credentials, .env files, binary dependencies or workstation-specific paths. Do not choose a licence, merge main, deploy, change repository visibility or publish a timetable without explicit authorisation.

Do not invoke an AI/Codex service as part of tests. CI must work from a fresh checkout without a home workstation. Keep generated schemas/fixtures/evidence separate from tracked source. Tests and benchmarks must report what actually executed.
