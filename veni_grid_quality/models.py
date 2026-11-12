"""Q1 candidate quality score policy, additive to the immutable C1 input contract.

A metric is an explicitly selected penalty. No default policies, hidden weights,
solver optimality, or publication authority are implied.
"""
from __future__ import annotations
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from veni_grid_contract.models import ID


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class MetricBase(Strict):
    id: ID
    tier: Literal[2, 3, 4]
    weight: int = Field(ge=1, le=1_000_000)


class ActivityPairs(MetricBase):
    kind: Literal['ACTIVITY_DAY_PAIRS'] = 'ACTIVITY_DAY_PAIRS'
    activity_ids: list[ID] = Field(min_length=1)


class ResourceIdle(MetricBase):
    kind: Literal['RESOURCE_IDLE_MINUTES'] = 'RESOURCE_IDLE_MINUTES'
    resource_ids: list[ID] = Field(min_length=1)


class DailySpread(MetricBase):
    kind: Literal['RESOURCE_DAILY_LOAD_SPREAD'] = 'RESOURCE_DAILY_LOAD_SPREAD'
    resource_ids: list[ID] = Field(min_length=1)
    day_ids: list[ID] = Field(min_length=1)


class TaggedPlacement(MetricBase):
    kind: Literal['TAGGED_PLACEMENTS'] = 'TAGGED_PLACEMENTS'
    event_ids: list[ID] = Field(min_length=1)
    tags: list[str] = Field(min_length=1)


class LocationChanges(MetricBase):
    kind: Literal['RESOURCE_LOCATION_CHANGES'] = 'RESOURCE_LOCATION_CHANGES'
    resource_ids: list[ID] = Field(min_length=1)


class UnmetRequests(MetricBase):
    kind: Literal['UNMET_SOFT_REQUESTS'] = 'UNMET_SOFT_REQUESTS'
    request_ids: list[ID] = Field(min_length=1)


Metric = Annotated[
    ActivityPairs | ResourceIdle | DailySpread | TaggedPlacement | LocationChanges | UnmetRequests,
    Field(discriminator='kind'),
]


class QualityPolicy(Strict):
    version: Literal['0.1.0'] = '0.1.0'
    id: ID
    model_sha256: str = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]{64}$')
    metrics: list[Metric] = Field(min_length=1)

    @model_validator(mode='after')
    def no_duplicates(self):
        if len({m.id for m in self.metrics}) != len(self.metrics):
            raise ValueError('Duplicate metric ID')
        return self


class QualityComponent(Strict):
    metric_id: ID
    kind: str
    tier: int
    unit: str
    raw_penalty: int
    weight: int
    weighted_penalty: int
    contributions: dict[str, int] = Field(default_factory=dict)


class QualityResult(Strict):
    evaluator_version: Literal['0.1.0'] = '0.1.0'
    status: Literal['SCORED', 'INCOMPLETE_SCORING', 'INVALID_INPUT', 'INVALID_CANDIDATE', 'UNRESOLVED_CONTEXT']
    policy_id: str | None = None
    policy_sha256: str | None = None
    model_sha256: str | None = None
    candidate_sha256: str | None = None
    model_version: int | None = None
    components: list[QualityComponent] = Field(default_factory=list)
    tier_penalties: dict[int, int] = Field(default_factory=dict)
    lexicographic_vector: list[int] = Field(default_factory=list)
    unscored_soft_rule_ids: list[str] = Field(default_factory=list)
    unscored_objective_ids: list[str] = Field(default_factory=list)
    unscored_soft_request_ids: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    hard_validation: Literal['NOT_RUN','PASSED','FAILED'] = 'NOT_RUN'
    quality_optimality: Literal['NOT_ASSESSED'] = 'NOT_ASSESSED'
    publication: Literal['NOT_GRANTED'] = 'NOT_GRANTED'


class Comparison(Strict):
    status: Literal['COMPARABLE', 'INCOMPARABLE']
    winner: Literal['LEFT', 'RIGHT', 'TIE'] | None = None
    reason: str = ''
    left_vector: list[int] = Field(default_factory=list)
    right_vector: list[int] = Field(default_factory=list)
