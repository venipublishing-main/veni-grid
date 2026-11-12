"""Veni Grid cross-vertical CANONICAL CONTRACT — 0.3 DRAFT. Not a solver.

The core has no School/Exam/Invigilation special-case types. Domain terms live in
labels, annotation tags and vertical adapters. Explicit placement domains make all
synthetic fixtures small, transparent and deterministic.
"""
from __future__ import annotations

from datetime import date as CalendarDate
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ID = Annotated[str, Field(min_length=2, pattern=r"^[A-Za-z][A-Za-z0-9_.:-]*$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResourceKind(str, Enum):
    PERSON = "PERSON"
    GROUP = "GROUP"
    SPACE = "SPACE"
    TEAM = "TEAM"
    EQUIPMENT = "EQUIPMENT"
    POOL = "POOL"
    OTHER = "OTHER"


class RuleStrength(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"


class RuleSource(str, Enum):
    SYSTEM = "SYSTEM"
    VERTICAL_DEFAULT = "VERTICAL_DEFAULT"
    IMPORT = "IMPORT"
    USER = "USER"
    USER_LOCK = "USER_LOCK"
    AI_INTERPRETED = "AI_INTERPRETED"


class Day(StrictModel):
    id: ID
    label: str
    ordinal: int = Field(ge=0)
    date: CalendarDate | None = None


class TimeWindow(StrictModel):
    id: ID
    day_id: ID
    bell_id: ID
    sequence: int = Field(ge=1)
    start_minute: int = Field(ge=0, lt=1440)
    end_minute: int = Field(gt=0, le=1440)
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ordered(self):
        if self.end_minute <= self.start_minute:
            raise ValueError("end_minute must follow start_minute")
        return self


class Resource(StrictModel):
    id: ID
    kind: ResourceKind
    label: str
    tags: list[str] = Field(default_factory=list)
    member_ids: list[ID] = Field(default_factory=list)
    capacity: int | None = Field(default=None, ge=1)
    unavailable_window_ids: list[ID] = Field(default_factory=list)
    sharing_mode: Literal["EXCLUSIVE", "CUMULATIVE"] = "EXCLUSIVE"

    @model_validator(mode="after")
    def sharing_valid(self):
        if self.sharing_mode == "CUMULATIVE":
            if self.kind not in (ResourceKind.SPACE, ResourceKind.EQUIPMENT, ResourceKind.POOL):
                raise ValueError("Only physical spaces/equipment/pools may share capacity")
            if self.capacity is None:
                raise ValueError("Cumulative resource needs an explicit capacity")
        return self


class Demand(StrictModel):
    basis: Literal["GLOBAL", "PER_ENROLLED"]
    unit: Literal["WINDOWS", "MINUTES"]
    amount: int = Field(ge=1)


class Activity(StrictModel):
    id: ID
    label: str
    demand: Demand
    tags: list[str] = Field(default_factory=list)


class WindowDuration(StrictModel):
    unit: Literal["WINDOWS"] = "WINDOWS"
    count: int = Field(ge=1)
    max_gap_minutes: int = Field(default=0, ge=0)


class MinuteDuration(StrictModel):
    unit: Literal["MINUTES"] = "MINUTES"
    count: int = Field(ge=1)


Duration = Annotated[WindowDuration | MinuteDuration, Field(discriminator="unit")]


class ResourceRequirement(StrictModel):
    id: ID
    role: str = Field(min_length=1)
    kind: ResourceKind
    quantity: int = Field(ge=1)
    eligible_resource_ids: list[ID] = Field(min_length=1)
    minimum_capacity: int | None = Field(default=None, ge=1)
    usage_units: int | None = Field(default=None, ge=1)


class PlacementDomain(StrictModel):
    start_window_ids: list[ID] = Field(min_length=1)


class Event(StrictModel):
    id: ID
    label: str
    activity_id: ID
    offering_id: ID | None = None
    required: bool = True
    fixed_participant_ids: list[ID] = Field(default_factory=list)
    duration: Duration
    placement: PlacementDomain
    requirements: list[ResourceRequirement] = Field(default_factory=list)


class Offering(StrictModel):
    id: ID
    activity_id: ID
    event_ids: list[ID] = Field(min_length=1)
    capacity: int = Field(ge=1)
    activation: Literal["ON_ENROLLMENT"] = "ON_ENROLLMENT"


class ParticipationRequest(StrictModel):
    id: ID
    participant_id: ID
    activity_id: ID
    eligible_offering_ids: list[ID] = Field(min_length=1)
    min_select: int = Field(default=1, ge=0)
    max_select: int = Field(default=1, ge=1)
    strength: RuleStrength = RuleStrength.HARD
    priority: int = Field(default=2, ge=1, le=4)

    @model_validator(mode="after")
    def bounds(self):
        if self.min_select > self.max_select:
            raise ValueError("min_select exceeds max_select")
        if self.max_select > len(set(self.eligible_offering_ids)):
            raise ValueError("max_select exceeds number of eligible offerings")
        return self


class RuleBase(StrictModel):
    id: ID
    strength: RuleStrength
    source: RuleSource
    enabled: bool = True
    priority: int = Field(default=3, ge=0, le=4)
    weight: int = Field(default=1, ge=1)


class ResourceBlackout(RuleBase):
    kind: Literal["RESOURCE_BLACKOUT"] = "RESOURCE_BLACKOUT"
    resource_id: ID
    window_ids: list[ID] = Field(min_length=1)


class ExcludeFromEvent(RuleBase):
    kind: Literal["EXCLUDE_RESOURCE_FROM_EVENT"] = "EXCLUDE_RESOURCE_FROM_EVENT"
    event_ids: list[ID] = Field(min_length=1)
    resource_ids: list[ID] = Field(min_length=1)
    role: str | None = None


class MaxDailyMinutes(RuleBase):
    kind: Literal["MAX_DAILY_MINUTES"] = "MAX_DAILY_MINUTES"
    resource_ids: list[ID] = Field(min_length=1)
    limit_minutes: int = Field(ge=1)


class WorkloadBalance(RuleBase):
    kind: Literal["WORKLOAD_BALANCE"] = "WORKLOAD_BALANCE"
    resource_ids: list[ID] = Field(min_length=2)
    metric: Literal["ASSIGNMENT_COUNT", "DUTY_MINUTES"]
    target_spread: int = Field(ge=0)


class ActivitySpread(RuleBase):
    kind: Literal["ACTIVITY_SPREAD"] = "ACTIVITY_SPREAD"
    activity_ids: list[ID] = Field(min_length=1)
    minimum_distinct_days: int = Field(ge=1)


class EventOrdering(RuleBase):
    kind: Literal["EVENT_BEFORE"] = "EVENT_BEFORE"
    earlier_event_id: ID
    later_event_id: ID
    minimum_gap_minutes: int = Field(default=0, ge=0)


class EventNotTogether(RuleBase):
    kind: Literal["EVENT_NOT_SAME_TIME"] = "EVENT_NOT_SAME_TIME"
    event_ids: list[ID] = Field(min_length=2)


Rule = Annotated[
    ResourceBlackout | ExcludeFromEvent | MaxDailyMinutes | WorkloadBalance
    | ActivitySpread | EventOrdering | EventNotTogether,
    Field(discriminator="kind"),
]


class Objective(StrictModel):
    id: ID
    tier: int = Field(ge=1, le=4)
    metric: Literal[
        "BASELINE_CHANGES", "CRITICAL_RULE_PENALTY", "GENERAL_RULE_PENALTY",
        "AESTHETIC_RULE_PENALTY", "UNMET_PARTICIPATION_REQUESTS"
    ]
    weight: int = Field(ge=1)


class Lock(StrictModel):
    id: ID
    event_id: ID
    start_window_id: ID | None = None
    requirement_id: ID | None = None
    resource_ids: list[ID] = Field(default_factory=list)
    source: Literal["USER_LOCK", "SYSTEM"] = "USER_LOCK"

    @model_validator(mode="after")
    def meaningful(self):
        if not self.start_window_id and not (self.requirement_id and self.resource_ids):
            raise ValueError("lock must fix a start window or a resource allocation")
        return self


class SolveConfig(StrictModel):
    mode: Literal["FEASIBILITY", "OPTIMISE", "REPAIR", "DIAGNOSE", "COMPARE"] = "FEASIBILITY"
    time_limit_seconds: int = Field(default=30, ge=1)
    random_seed: int = 1
    deterministic: bool = True


class SchedulingProblem(StrictModel):
    schema_version: Literal["0.3.0-draft"] = "0.3.0-draft"
    problem_id: ID
    model_version: int = Field(ge=1)
    vertical_id: str = Field(min_length=1)
    timezone: str = "Africa/Johannesburg"
    days: list[Day] = Field(min_length=1)
    windows: list[TimeWindow] = Field(min_length=1)
    resources: list[Resource] = Field(min_length=1)
    activities: list[Activity] = Field(min_length=1)
    events: list[Event] = Field(min_length=1)
    offerings: list[Offering] = Field(default_factory=list)
    participation_requests: list[ParticipationRequest] = Field(default_factory=list)
    constraints: list[Rule] = Field(default_factory=list)
    objectives: list[Objective] = Field(default_factory=list)
    locks: list[Lock] = Field(default_factory=list)
    baseline_solution_id: ID | None = None
    solve_config: SolveConfig = Field(default_factory=SolveConfig)


class RequirementAllocation(StrictModel):
    requirement_id: ID
    resource_ids: list[ID] = Field(min_length=1)


class EventAssignment(StrictModel):
    event_id: ID
    start_window_id: ID
    resource_allocations: list[RequirementAllocation] = Field(default_factory=list)


class EnrollmentAssignment(StrictModel):
    request_id: ID
    offering_ids: list[ID] = Field(default_factory=list)


class SchedulingSolution(StrictModel):
    schema_version: Literal["0.3.0-draft"] = "0.3.0-draft"
    solution_id: ID
    problem_id: ID
    model_version: int = Field(ge=1)
    status: Literal["FEASIBLE", "OPTIMAL", "INFEASIBLE", "UNKNOWN", "INVALID_INPUT", "ERROR"]
    event_assignments: list[EventAssignment] = Field(default_factory=list)
    enrollment_assignments: list[EnrollmentAssignment] = Field(default_factory=list)
    validation: Literal["UNVALIDATED", "PASSED", "FAILED"] = "UNVALIDATED"
