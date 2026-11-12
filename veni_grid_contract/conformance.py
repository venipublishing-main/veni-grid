"""One honest review entry point and machine-readable implementation boundaries.

Profiles isolate implementation milestones, not separate products or mandatory
execution dependencies. No solver backend is registered by this design package.
"""
from __future__ import annotations
from typing import Literal
from pydantic import Field
from .primitives import ContractModel, Finding
from .core_v1 import CoreProblem, CoreWitness, core_problem_errors, core_witness_errors

HARD_RULES = (
    'RESOURCE_BLACKOUT','EXCLUDE_RESOURCE_FROM_EVENT','MAX_DAILY_MINUTES',
    'WORKLOAD_BALANCE','ACTIVITY_SPREAD','EVENT_BEFORE','EVENT_NOT_SAME_TIME',
    'EVENT_SAME_START','QUALIFICATION','RESOURCE_CONTINUITY','TRAVEL_TIME',
)

CONFORMANCE_PROFILES = {
    'C1_PLACEMENT': {
        'schema_version':'1.0.0-rc1', 'standalone':True,
        'mandatory_other_timetables':[], 'hard_rule_kinds':list(HARD_RULES),
        'witness_validation':'IMPLEMENTED', 'solver_compilation':'NOT_IMPLEMENTED',
        'soft_scoring':'NOT_IMPLEMENTED', 'publication':'NOT_IMPLEMENTED',
        'limits':['Travel within the same local day for supplied target events only',
                  'Fixed membership snapshot; effective-dated membership requires another model revision',
                  'No overnight lesson windows', 'One scalar cumulative capacity per resource'],
    },
    'I1_COVERAGE': {
        'schema_version':'0.3.0-draft', 'handoff_schema_version':'0.4.0-draft',
        'standalone':True, 'mandatory_other_timetables':[],
        'witness_validation':'IMPLEMENTED', 'solver_compilation':'NOT_IMPLEMENTED',
        'soft_scoring':'NOT_IMPLEMENTED','publication':'NOT_IMPLEMENTED',
        'limits':['Fixed sessions; explicit eligibility and time-varying role minima',
                  'New C1 qualification/travel rules are not yet integrated in this coverage profile'],
    },
    'O1_OPTION_DESIGN': {
        'schema_version':'0.3.0-draft','standalone':True,'mandatory_other_timetables':[],
        'witness_validation':'IMPLEMENTED','solver_compilation':'NOT_IMPLEMENTED',
        'soft_scoring':'NOT_IMPLEMENTED','publication':'NOT_IMPLEMENTED',
        'limits':['Supplied section/block witnesses, not automatically generated plans',
                  'Teacher/room feasibility requires the separate lesson-placement stage'],
    },
}


class CoreReview(ContractModel):
    contract_version: Literal['1.0.0-rc1']='1.0.0-rc1'
    profile: Literal['C1_PLACEMENT']='C1_PLACEMENT'
    result: Literal['INPUT_VALIDATED_NOT_SOLVED','INVALID_INPUT','CANDIDATE_HARD_VALIDATED','CANDIDATE_INVALID']
    findings: list[Finding]=Field(default_factory=list)
    solver_execution: Literal['NOT_RUN']='NOT_RUN'
    soft_scoring: Literal['NOT_PERFORMED']='NOT_PERFORMED'
    publish_permission: Literal['NOT_GRANTED']='NOT_GRANTED'
    validity_scope: Literal['SUPPLIED_MODEL_ONLY']='SUPPLIED_MODEL_ONLY'


def review_core(problem: CoreProblem, witness: CoreWitness | None=None) -> CoreReview:
    errors=core_problem_errors(problem)
    if errors:return CoreReview(result='INVALID_INPUT',findings=errors)
    if witness is None:return CoreReview(result='INPUT_VALIDATED_NOT_SOLVED')
    errors=core_witness_errors(problem,witness)
    return CoreReview(result='CANDIDATE_INVALID' if errors else 'CANDIDATE_HARD_VALIDATED', findings=errors)


def execution_gate(profile: str, operation: str) -> list[Finding]:
    """Do not let a future caller mistake schema support for a registered solver."""
    if profile not in CONFORMANCE_PROFILES:
        return [Finding(code='UNSUPPORTED_PROFILE',detail=profile)]
    if operation not in {'FEASIBILITY','OPTIMISE','REPAIR','DIAGNOSE','COMPARE'}:
        return [Finding(code='UNSUPPORTED_OPERATION',detail=operation)]
    return [Finding(code='SOLVER_NOT_IMPLEMENTED', detail=f'{profile}/{operation}: contract review only')]
