"""Public C1 solve boundary: capability gate -> compile -> solve -> independent check."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from time import perf_counter
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from veni_grid_contract.core_v1 import CoreProblem, CoreWitness, core_problem_errors
from veni_grid_contract.conformance import review_core
from veni_grid_contract.primitives import Finding


class SolverOptions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    max_time_seconds: float | None = Field(default=None, ge=0, le=300)
    max_deterministic_time: float | None = Field(default=None, ge=0)
    workers: int = Field(default=1, ge=1, le=8)


class SolveResult(BaseModel):
    model_config = ConfigDict(extra='forbid')
    runtime_version: str = '0.1.0'
    contract_version: str = '1.0.0-rc1'
    profile: str = 'C1_PLACEMENT'
    status: Literal['FEASIBLE','INFEASIBLE','UNKNOWN','INVALID_INPUT','UNSUPPORTED','ERROR']
    solver_status: str = 'NOT_RUN'
    backend: str = 'OR_TOOLS_CP_SAT'
    backend_version: str | None = None
    model_hash: str | None = None
    compiled_model_hash: str | None = None
    problem_id: str | None = None
    model_version: int | None = None
    configuration: dict[str, Any] = Field(default_factory=dict)
    candidate: CoreWitness | None = None
    validation: Literal['NOT_RUN','PASSED','FAILED'] = 'NOT_RUN'
    findings: list[Finding] = Field(default_factory=list)
    ignored_soft_rule_ids: list[str] = Field(default_factory=list)
    ignored_objective_ids: list[str] = Field(default_factory=list)
    soft_request_ids: list[str] = Field(default_factory=list)
    solver_statistics: dict[str, Any] = Field(default_factory=dict)
    compilation_ms: float = 0
    solve_ms: float = 0
    validation_ms: float = 0
    total_ms: float = 0
    started_at: str
    proven_infeasible: bool = False
    quality_optimality: Literal['NOT_ASSESSED'] = 'NOT_ASSESSED'
    soft_scoring: Literal['NOT_PERFORMED'] = 'NOT_PERFORMED'
    publish_permission: Literal['NOT_GRANTED'] = 'NOT_GRANTED'
    validity_scope: Literal['SUPPLIED_C1_MODEL_ONLY'] = 'SUPPLIED_C1_MODEL_ONLY'


def solve(problem: CoreProblem | dict, options: SolverOptions | dict | None = None) -> SolveResult:
    """Find hard-feasible assignments only; does not mutate, repair or publish."""
    started=perf_counter()
    result=SolveResult(status='ERROR',started_at=datetime.now(timezone.utc).isoformat())
    def finish():
        result.total_ms=round((perf_counter()-started)*1000,3)
        return result
    try:
        data = problem.model_dump(mode='json') if isinstance(problem, CoreProblem) else problem
        # JSON-mode strict parsing preserves valid ISO dates/enums while refusing
        # booleans/numeric strings in integer fields. Import normalisation is separate.
        p=CoreProblem.model_validate_json(json.dumps(data, allow_nan=False), strict=True)
        opts=SolverOptions.model_validate(options.model_dump() if isinstance(options,SolverOptions) else (options or {}), strict=True)
        errors=core_problem_errors(p)
        if errors:
            result.status='INVALID_INPUT';result.findings=errors;return finish()
    except (ValidationError,ValueError,TypeError,KeyError) as exc:
        result.status='INVALID_INPUT';result.findings=[Finding(code='INVALID_CANONICAL_INPUT',detail=str(exc))];return finish()
    result.problem_id=p.problem_id;result.model_version=p.model_version
    raw=json.dumps(p.model_dump(mode='json'),sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
    result.model_hash=hashlib.sha256(raw).hexdigest()
    if p.solve_config.mode!='FEASIBILITY':
        result.status='UNSUPPORTED';result.findings=[Finding(code='UNSUPPORTED_MODE',detail=p.solve_config.mode)];return finish()
    if p.baseline_solution_id is not None:
        result.status='UNSUPPORTED';result.findings=[Finding(code='BASELINE_REPAIR_NOT_SUPPORTED',detail='No implicit preservation or repair from a baseline ID')];return finish()
    if p.solve_config.deterministic and opts.workers!=1:
        result.status='UNSUPPORTED';result.findings=[Finding(code='DETERMINISTIC_WORKER_CONFLICT',detail='Use one worker for the deterministic profile')];return finish()
    if not 0 <= p.solve_config.random_seed < 2**31:
        result.status='INVALID_INPUT';result.findings=[Finding(code='INVALID_RANDOM_SEED',detail='CP-SAT requires an integer in [0, 2^31)')];return finish()
    result.ignored_soft_rule_ids=[r.id for r in p.constraints if r.enabled and r.strength=='SOFT']
    result.ignored_objective_ids=[o.id for o in p.objectives]
    result.soft_request_ids=[q.id for q in p.participation_requests if q.strength=='SOFT']
    if result.ignored_soft_rule_ids or result.ignored_objective_ids or result.soft_request_ids:
        result.findings.append(Finding(code='SOFT_NOT_EVALUATED',detail='FEASIBILITY enforces hard rules and request bounds; no preference score or optimality claim'))
    try:
        import ortools
        from ortools.sat.python import cp_model
        from .compiler import Compiler, UnsupportedInput
    except ImportError as exc:
        result.findings.append(Finding(code='BACKEND_UNAVAILABLE',detail=str(exc)));return finish()
    result.backend_version=ortools.__version__
    try:
        t=perf_counter(); compiled=Compiler(p).compile();result.compilation_ms=round((perf_counter()-t)*1000,3)
        # Model validation failures are compiler errors, never blamed on canonical input.
        model_error=compiled.m.validate()
        if model_error:
            result.solver_status='MODEL_INVALID'
            result.findings.append(Finding(code='COMPILED_MODEL_INVALID',detail=model_error));return finish()
        # Text representation is recorded for this backend version, not claimed cross-version canonical.
        result.compiled_model_hash=hashlib.sha256(str(compiled.m.proto).encode()).hexdigest()
        engine=cp_model.CpSolver()
        limit=min(float(p.solve_config.time_limit_seconds),opts.max_time_seconds) if opts.max_time_seconds is not None else float(p.solve_config.time_limit_seconds)
        engine.parameters.max_time_in_seconds=limit
        engine.parameters.num_search_workers=opts.workers
        engine.parameters.random_seed=p.solve_config.random_seed
        if opts.max_deterministic_time is not None:engine.parameters.max_deterministic_time=opts.max_deterministic_time
        result.configuration={'mode':'FEASIBILITY','max_time_seconds':limit,'max_deterministic_time':opts.max_deterministic_time,
                              'workers':opts.workers,'random_seed':p.solve_config.random_seed,'deterministic':p.solve_config.deterministic}
        t=perf_counter();status=engine.solve(compiled.m);result.solve_ms=round((perf_counter()-t)*1000,3)
        result.solver_status=engine.status_name(status)
        result.solver_statistics={'branches':engine.num_branches,'conflicts':engine.num_conflicts,'wall_time_seconds':engine.wall_time,
                                  'model':compiled.m.model_stats(),'response':engine.response_stats()}
        if status in (cp_model.OPTIMAL,cp_model.FEASIBLE):
            candidate=compiled.extract(engine,result.model_hash)
            t=perf_counter();checked=review_core(p,candidate);result.validation_ms=round((perf_counter()-t)*1000,3)
            if checked.result!='CANDIDATE_HARD_VALIDATED':
                result.validation='FAILED';result.findings.extend(checked.findings)
                result.findings.append(Finding(code='SOLVER_VALIDATOR_DISAGREEMENT',detail='Candidate withheld; compiler/extractor investigation required'))
            else:
                result.status='FEASIBLE';result.validation='PASSED';result.candidate=candidate
        elif status==cp_model.INFEASIBLE:
            result.status='INFEASIBLE';result.proven_infeasible=True
            result.findings.append(Finding(code='PROVED_INFEASIBLE',detail='No assignment satisfies the compiled supported model; no minimal conflict-set claim'))
        elif status==cp_model.UNKNOWN:result.status='UNKNOWN'
        elif status==cp_model.MODEL_INVALID:
            result.findings.append(Finding(code='COMPILED_MODEL_INVALID',detail=engine.solution_info()))
        else:result.findings.append(Finding(code='UNEXPECTED_SOLVER_STATUS',detail=str(status)))
        for note in compiled.notes:result.findings.append(Finding(code='DOMAIN_NOTE',detail=note))
    except UnsupportedInput as exc:
        result.status='UNSUPPORTED';result.findings.append(Finding(code=exc.code,detail=exc.detail))
    except Exception as exc:
        result.status='ERROR';result.findings.append(Finding(code='RUNTIME_ERROR',detail=f'{type(exc).__name__}: {exc}'))
    return finish()
