"""Demand-to-offering DESIGN contract. No sections or option blocks pre-assigned in input.

A witness is proposed externally, then checked here. This does NOT generate a plan,
assign teachers/rooms, optimise requests, or prove infeasibility.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from typing import Literal
from pydantic import Field, model_validator
from .models import ID
from .primitives import ContractModel, Positive, Finding, unique_errors

class OfferingFamily(ContractModel):
    id: ID
    label: str
    min_members: Positive = 1
    max_members: Positive
    max_sections: Positive
    @model_validator(mode="after")
    def bounds(self):
        if self.min_members>self.max_members: raise ValueError("Invalid member bounds")
        return self

class ChoiceDemand(ContractModel):
    id: ID
    participant_id: ID
    family_id: ID

class OptionDesignProblem(ContractModel):
    schema_version: Literal["0.3.0-draft"] = "0.3.0-draft"
    problem_id: ID
    model_version: Positive
    participant_ids: list[ID] = Field(min_length=1)
    families: list[OfferingFamily] = Field(min_length=1)
    requests: list[ChoiceDemand] = Field(min_length=1)
    max_blocks: Positive

class DesignedOffering(ContractModel):
    id: ID
    family_id: ID
    block_id: ID

class ChoiceAllocation(ContractModel):
    request_id: ID
    offering_id: ID

class OptionDesignWitness(ContractModel):
    schema_version: Literal["0.3.0-draft"] = "0.3.0-draft"
    problem_id: ID
    model_version: Positive
    block_ids: list[ID] = Field(min_length=1)
    offerings: list[DesignedOffering] = Field(min_length=1)
    allocations: list[ChoiceAllocation]


def option_errors(p: OptionDesignProblem, w: OptionDesignWitness) -> list[Finding]:
    errors=unique_errors(p.families,"families")+unique_errors(p.requests,"requests")+unique_errors(w.offerings,"offerings")
    def bad(code,detail): errors.append(Finding(code=code,detail=detail))
    if (p.problem_id,p.model_version)!=(w.problem_id,w.model_version): bad("STALE_OPTION_PLAN",p.problem_id)
    if len(p.participant_ids)!=len(set(p.participant_ids)): bad("DUPLICATE_PARTICIPANT","participants")
    if len(w.block_ids)!=len(set(w.block_ids)) or len(w.block_ids)>p.max_blocks: bad("INVALID_BLOCKS","blocks")
    families={f.id:f for f in p.families};requests={r.id:r for r in p.requests};offers={o.id:o for o in w.offerings}
    pairs=set()
    for r in p.requests:
        if r.participant_id not in p.participant_ids or r.family_id not in families: bad("BROKEN_CHOICE_REQUEST",r.id)
        key=(r.participant_id,r.family_id)
        if key in pairs: bad("DUPLICATE_CHOICE_REQUEST",r.id)
        pairs.add(key)
    totals=Counter(o.family_id for o in w.offerings)
    for o in w.offerings:
        if o.family_id not in families or o.block_id not in w.block_ids: bad("BROKEN_OFFERING",o.id)
    for fid,count in totals.items():
        if fid in families and count>families[fid].max_sections: bad("SECTION_LIMIT",fid)
    seen=set();members=defaultdict(set);attendance={}
    for a in w.allocations:
        r=requests.get(a.request_id);o=offers.get(a.offering_id)
        if a.request_id in seen: bad("DUPLICATE_CHOICE_ALLOCATION",a.request_id)
        seen.add(a.request_id)
        if not r or not o: bad("UNKNOWN_CHOICE_ALLOCATION",a.request_id);continue
        if o.family_id!=r.family_id: bad("WRONG_SUBJECT",a.request_id)
        members[o.id].add(r.participant_id)
        key=(r.participant_id,o.block_id)
        if key in attendance: bad("LEARNER_BLOCK_CLASH",r.participant_id)
        attendance[key]=o.id
    if seen != set(requests): bad("UNFULFILLED_REQUESTS",str(sorted(set(requests)-seen)))
    for oid,o in offers.items():
        f=families.get(o.family_id)
        if f and not (f.min_members<=len(members[oid])<=f.max_members): bad("SECTION_CAPACITY",oid)
    return errors
