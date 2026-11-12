"""Example Q1 policy for synthetic Benchmark B, not a platform default."""
from __future__ import annotations
from veni_grid_contract.core_v1 import CoreProblem
from .evaluate import digest
from .models import QualityPolicy


def benchmark_b_policy(problem: CoreProblem) -> QualityPolicy:
    educators = sorted(r.id for r in problem.resources if r.kind == 'PERSON' and
        r.id.startswith(('person:MATH', 'person:ENG', 'person:SCI', 'person:HIST', 'person:LIFE')))
    return QualityPolicy.model_validate({'id':'policy:B:comparison','model_sha256':digest(problem),
        'metrics':[
            {'id':'q:activity-distribution','kind':'ACTIVITY_DAY_PAIRS','tier':2,'weight':5,
             'activity_ids':[a.id for a in problem.activities]},
            {'id':'q:staff-idle','kind':'RESOURCE_IDLE_MINUTES','tier':3,'weight':1,
             'resource_ids':educators},
            {'id':'q:staff-load','kind':'RESOURCE_DAILY_LOAD_SPREAD','tier':3,'weight':1,
             'resource_ids':educators,'day_ids':[d.id for d in problem.days]},
            {'id':'q:room-movement','kind':'RESOURCE_LOCATION_CHANGES','tier':3,'weight':5,
             'resource_ids':educators},
            {'id':'q:late','kind':'TAGGED_PLACEMENTS','tier':4,'weight':10,
             'event_ids':[e.id for e in problem.events],'tags':['FINAL']},
        ]})
