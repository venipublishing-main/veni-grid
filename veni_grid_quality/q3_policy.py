"""Q3 experimental policy 0.2.0: protect nonteaching breaks and respect staff load targets.

Q1 and Q2 policies remain unchanged, version-pinned and reproducible.
The break objective initially supports ABSTRACT CYCLE days only; dated calendars
require a separate timezone-aware profile and are rejected rather than guessed.
"""
from __future__ import annotations
from typing import Annotated, Literal
from pydantic import Field, model_validator
from .models import (
    Strict, MetricBase, QualityPolicy, ActivityPairs, ResourceIdle, DailySpread,
    TaggedPlacement, LocationChanges, UnmetRequests,
)
from veni_grid_contract.models import ID


class ProtectedBreak(Strict):
    resource_id: ID
    day_id: ID
    start_minute: int = Field(ge=0, le=1440)
    end_minute: int = Field(ge=0, le=1440)

    @model_validator(mode='after')
    def valid_interval(self):
        if self.end_minute <= self.start_minute:
            raise ValueError('Protected break end must be after start')
        return self


class ProtectedIdle(MetricBase):
    kind: Literal['RESOURCE_UNPROTECTED_IDLE_MINUTES'] = 'RESOURCE_UNPROTECTED_IDLE_MINUTES'
    resource_ids: list[ID] = Field(min_length=1)
    protected_breaks: list[ProtectedBreak] = Field(default_factory=list)


class LoadTarget(Strict):
    resource_id: ID
    day_id: ID
    target_minutes: int = Field(ge=0, le=1440)


class TargetLoadDeviation(MetricBase):
    kind: Literal['RESOURCE_TARGET_DAILY_LOAD_DEVIATION'] = 'RESOURCE_TARGET_DAILY_LOAD_DEVIATION'
    targets: list[LoadTarget] = Field(min_length=1)


Q3Metric = Annotated[
    ActivityPairs | ResourceIdle | DailySpread | TaggedPlacement | LocationChanges |
    UnmetRequests | ProtectedIdle | TargetLoadDeviation,
    Field(discriminator='kind'),
]


class QualityPolicyV2(QualityPolicy):
    version: Literal['0.2.0'] = '0.2.0'
    metrics: list[Q3Metric] = Field(min_length=1)

    @model_validator(mode='after')
    def q3_unique_scopes(self):
        for metric in self.metrics:
            if isinstance(metric, ProtectedIdle):
                if len(set(metric.resource_ids)) != len(metric.resource_ids):
                    raise ValueError(f'{metric.id}: duplicate resource IDs')
                per_key = {}
                for b in metric.protected_breaks:
                    if b.resource_id not in metric.resource_ids:
                        raise ValueError(f'{metric.id}: break for unscoped person {b.resource_id}')
                    per_key.setdefault((b.resource_id, b.day_id), []).append((b.start_minute, b.end_minute))
                for key, spans in per_key.items():
                    spans.sort()
                    if any(a[1] > b[0] for a,b in zip(spans,spans[1:])):
                        raise ValueError(f'{metric.id}: overlapping protected intervals {key}')
            elif isinstance(metric, TargetLoadDeviation):
                keys=[(t.resource_id,t.day_id) for t in metric.targets]
                if len(set(keys)) != len(keys):
                    raise ValueError(f'{metric.id}: duplicate person/day load target')
        return self
