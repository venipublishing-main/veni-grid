"""On-demand scope and dependency contract. Validates proposals; never writes schedules."""
from __future__ import annotations
from typing import Literal
from pydantic import Field, JsonValue, model_validator
from .models import ID
from .primitives import (ContractModel, Positive, Interval, CapacityResource,
                         ResourceClaim, Finding, usage_errors)

ChangeField = Literal["TIME", "RESOURCES", "MEMBERSHIP", "ACTIVATION", "COVERAGE"]

class ScheduleVersion(ContractModel):
    schedule_id: ID
    revision: Positive
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

class MutableSlice(ContractModel):
    schedule_id: ID
    entity_ids: list[ID] = Field(min_length=1)
    fields: list[ChangeField] = Field(min_length=1)

class Dependency(ContractModel):
    source: ScheduleVersion
    claims: list[ResourceClaim] = Field(default_factory=list)

class SchedulingJob(ContractModel):
    schema_version: Literal["0.3.0-draft"] = "0.3.0-draft"
    job_id: ID
    purpose: str
    mode: Literal["STANDALONE", "RESPECT_EXISTING", "JOINT"] = "STANDALONE"
    targets: list[ScheduleVersion] = Field(min_length=1)
    mutable: list[MutableSlice] = Field(min_length=1)
    horizon: Interval | None = None
    dependencies: list[Dependency] = Field(default_factory=list)
    preserved_claims: list[ResourceClaim] = Field(default_factory=list)
    joint_authorised: bool = False
    resources: list[CapacityResource] = Field(default_factory=list)

    @model_validator(mode="after")
    def scope_valid(self):
        tids=[t.schedule_id for t in self.targets]
        dids=[d.source.schedule_id for d in self.dependencies]
        if len(set(tids))!=len(tids) or len(set(dids))!=len(dids):
            raise ValueError("Repeated schedule scope")
        if set(tids)&set(dids):
            raise ValueError("Read-only dependency cannot also be a writable target")
        if self.mode=="STANDALONE" and (len(tids)!=1 or self.dependencies):
            raise ValueError("Standalone has exactly one target and no linked dependencies")
        if self.mode=="RESPECT_EXISTING" and (len(tids)!=1 or not self.dependencies):
            raise ValueError("Linked independent job has one target and named read-only sources")
        if self.mode=="JOINT" and (len(tids)<2 or not self.joint_authorised):
            raise ValueError("Joint work requires explicit authorisation and at least two targets")
        if self.mode!="JOINT" and self.joint_authorised:
            raise ValueError("joint_authorised is only meaningful for JOINT jobs")
        if {m.schedule_id for m in self.mutable} != set(tids):
            raise ValueError("Every and only target schedules need explicit mutable slices")
        for m in self.mutable:
            if len(set(m.entity_ids))!=len(m.entity_ids) or len(set(m.fields))!=len(m.fields):
                raise ValueError("Duplicate mutable entity/field")
        mutable_entities={(m.schedule_id,e) for m in self.mutable for e in m.entity_ids}
        for claim in self.preserved_claims:
            if claim.schedule_id not in tids or (claim.schedule_id,claim.entity_id) in mutable_entities:
                raise ValueError("Preserved claims must belong to untouched entities of a target")
        for d in self.dependencies:
            if any(c.schedule_id != d.source.schedule_id for c in d.claims):
                raise ValueError("Commitment source identity mismatch")
        return self

class ProposedChange(ContractModel):
    schedule_id: ID
    entity_id: ID
    field: ChangeField
    before: JsonValue
    after: JsonValue

class JobProposal(ContractModel):
    schema_version: Literal["0.3.0-draft"] = "0.3.0-draft"
    job_id: ID
    target_versions: list[ScheduleVersion]
    dependency_versions: list[ScheduleVersion] = Field(default_factory=list)
    changes: list[ProposedChange] = Field(default_factory=list)
    claims: list[ResourceClaim] = Field(default_factory=list)


def proposal_errors(job: SchedulingJob, proposal: JobProposal,
                    current_versions: list[ScheduleVersion]) -> list[Finding]:
    """Authorisation/identity/snapshot gate, not a full solution or security validator.

    current_versions must come from trusted storage at apply time, not the caller.
    The future writer must atomically compare-and-swap all target and source versions.
    """
    errors=[]
    def bad(code,detail): errors.append(Finding(code=code,detail=detail))
    if proposal.job_id!=job.job_id: bad("WRONG_JOB","Result is from another job")
    def versions(items):
        if len({x.schedule_id for x in items})!=len(items): bad("DUPLICATE_VERSION","Repeated schedule ID")
        return {x.schedule_id:(x.revision,x.content_sha256) for x in items}
    expected_targets=versions(job.targets)
    expected_deps=versions([d.source for d in job.dependencies])
    if versions(proposal.target_versions)!=expected_targets: bad("TARGET_VERSION_MISMATCH","Wrong baseline")
    if versions(proposal.dependency_versions)!=expected_deps: bad("DEPENDENCY_VERSION_MISMATCH","Wrong linked snapshots")
    current=versions(current_versions)
    for sid, ver in (expected_targets|expected_deps).items():
        if current.get(sid)!=ver: bad("STALE_SNAPSHOT",sid)
    allowed={(m.schedule_id,e,f) for m in job.mutable for e in m.entity_ids for f in m.fields}
    seen=set()
    for change in proposal.changes:
        key=(change.schedule_id,change.entity_id,change.field)
        if key not in allowed: bad("OUT_OF_SCOPE_CHANGE",str(key))
        if key in seen: bad("DUPLICATE_CHANGE",str(key))
        seen.add(key)
    target_entities={(m.schedule_id,e) for m in job.mutable for e in m.entity_ids}
    for claim in proposal.claims:
        if (claim.schedule_id,claim.entity_id) not in target_entities:
            bad("OUT_OF_SCOPE_CLAIM",claim.id)
        if job.horizon:
            from datetime import timezone
            if (claim.interval.start.astimezone(timezone.utc)<job.horizon.start.astimezone(timezone.utc)
                or claim.interval.end.astimezone(timezone.utc)>job.horizon.end.astimezone(timezone.utc)):
                bad("OUTSIDE_JOB_HORIZON",claim.id)
    linked=[c for d in job.dependencies for c in d.claims]
    errors.extend(usage_errors(job.resources,linked+job.preserved_claims+proposal.claims))
    return errors
