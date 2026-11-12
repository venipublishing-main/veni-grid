"""Shared interval/resource-usage checks, not an optimiser or publication service."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
from typing import Annotated, Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt, model_validator
from .models import ID

Positive = Annotated[StrictInt, Field(gt=0)]
NonNegative = Annotated[StrictInt, Field(ge=0)]

class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Interval(ContractModel):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def order(self):
        if self.start.astimezone(timezone.utc) >= self.end.astimezone(timezone.utc):
            raise ValueError("Interval requires positive elapsed time; endpoints must have offsets")
        return self

    def overlaps(self, other: "Interval") -> bool:
        a,b,c,d=(x.astimezone(timezone.utc) for x in (self.start,self.end,other.start,other.end))
        return a < d and c < b

    @property
    def minutes(self) -> float:
        return (self.end.astimezone(timezone.utc)-self.start.astimezone(timezone.utc)).total_seconds()/60

class CapacityResource(ContractModel):
    id: ID
    kind: Literal["PERSON", "SPACE", "EQUIPMENT", "POOL", "GROUP", "TEAM", "OTHER"]
    sharing: Literal["EXCLUSIVE", "CUMULATIVE"] = "EXCLUSIVE"
    capacity: Positive = 1
    unit: str = "USE"
    unavailable: list[Interval] = Field(default_factory=list)

    @model_validator(mode="after")
    def safe_sharing(self):
        if self.kind in ("PERSON", "GROUP", "TEAM", "OTHER") and self.sharing != "EXCLUSIVE":
            raise ValueError("People/groups cannot be capacity-shared")
        return self

class ResourceClaim(ContractModel):
    id: ID
    schedule_id: ID
    entity_id: ID
    resource_id: ID
    interval: Interval
    units: Positive = 1

class Finding(ContractModel):
    code: str
    detail: str

def unique_errors(items: list, label: str) -> list[Finding]:
    ids=[x.id for x in items]
    return [] if len(ids)==len(set(ids)) else [Finding(code="DUPLICATE_ID", detail=label)]

def usage_errors(resources: list[CapacityResource], claims: list[ResourceClaim]) -> list[Finding]:
    """Sweep ALL claim boundaries; half-open intervals make adjacent bookings legal."""
    errors=unique_errors(resources,"resources")+unique_errors(claims,"claims")
    catalog={r.id:r for r in resources}
    by_resource=defaultdict(list)
    for claim in claims:
        r=catalog.get(claim.resource_id)
        if r is None:
            errors.append(Finding(code="UNKNOWN_RESOURCE",detail=claim.resource_id)); continue
        if r.sharing=="EXCLUSIVE" and claim.units!=1:
            errors.append(Finding(code="BAD_EXCLUSIVE_UNITS",detail=claim.id))
        if any(claim.interval.overlaps(i) for i in r.unavailable):
            errors.append(Finding(code="RESOURCE_UNAVAILABLE",detail=claim.id))
        by_resource[r.id].append(claim)
    for rid, group in by_resource.items():
        r=catalog[rid]
        points=sorted({t.astimezone(timezone.utc) for c in group for t in (c.interval.start,c.interval.end)})
        for start,end in zip(points,points[1:]):
            active=[c for c in group if c.interval.start.astimezone(timezone.utc)<end and start<c.interval.end.astimezone(timezone.utc)]
            if r.sharing=="EXCLUSIVE" and len(active)>1:
                errors.append(Finding(code="RESOURCE_OVERLAP",detail=f"{rid}: {[c.id for c in active]} at {start.isoformat()}"))
            if r.sharing=="CUMULATIVE" and sum(c.units for c in active)>r.capacity:
                errors.append(Finding(code="CAPACITY_EXCEEDED",detail=f"{rid}: {sum(c.units for c in active)} > {r.capacity} at {start.isoformat()}"))
    return errors
