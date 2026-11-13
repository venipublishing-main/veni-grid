"""Independent Q3 candidate scorer, not an optimisation or publication service."""
from __future__ import annotations
from collections import defaultdict
from typing import Literal
import json
from datetime import timezone
from pydantic import ValidationError
from .evaluate import digest, score as q1score, verify_policy as verify_q1, ContextMissing
from .models import QualityPolicy, QualityResult, QualityComponent, Comparison
from .q3_policy import QualityPolicyV2, ProtectedIdle, TargetLoadDeviation
from veni_grid_contract.core_v1 import CoreProblem, CoreWitness, resolved_use, core_problem_errors
from veni_grid_contract.conformance import review_core
from veni_grid_contract.models import ResourceKind


class Q3Score(QualityResult):
    evaluator_version: Literal['0.2.0'] = '0.2.0'


def verify_q3_policy(p: CoreProblem, pol: QualityPolicyV2):
    rid={r.id:r for r in p.resources}
    did={d.id for d in p.days}
    for metric in pol.metrics:
        if isinstance(metric, ProtectedIdle):
            if any(d.date is not None for d in p.days):
                raise ContextMissing('Protected-break Q3 profile requires an abstract cycle (dated timezone profile pending)')
            for staff in metric.resource_ids:
                if staff not in rid or rid[staff].kind != ResourceKind.PERSON:
                    raise ValueError(f'{metric.id}: invalid PERSON {staff}')
            for b in metric.protected_breaks:
                if b.day_id not in did: raise ValueError(f'{metric.id}: unknown day {b.day_id}')
        elif isinstance(metric, TargetLoadDeviation):
            for t in metric.targets:
                if t.resource_id not in rid or rid[t.resource_id].kind != ResourceKind.PERSON:
                    raise ValueError(f'{metric.id}: invalid PERSON target {t.resource_id}')
                if t.day_id not in did:
                    raise ValueError(f'{metric.id}: unknown target day {t.day_id}')
    legacy = [m for m in pol.metrics if not isinstance(m,(ProtectedIdle,TargetLoadDeviation))]
    if legacy:
        verify_q1(p,QualityPolicy(id=pol.id, model_sha256=digest(p), metrics=legacy))


def overlap(a,b,c,d):
    return max(0,min(b,d)-max(a,c))


def score_v2(problem: CoreProblem | dict, witness: CoreWitness | dict,
             policy: QualityPolicyV2 | dict) -> Q3Score:
    out=Q3Score(status='INVALID_INPUT')
    try:
        p=CoreProblem.model_validate(problem.model_dump(mode='json') if isinstance(problem,CoreProblem) else problem)
        w=CoreWitness.model_validate(witness.model_dump(mode='json') if isinstance(witness,CoreWitness) else witness)
        pol=QualityPolicyV2.model_validate(policy.model_dump(mode='json') if isinstance(policy,QualityPolicyV2) else policy)
        out.model_sha256=digest(p); out.policy_sha256=digest(pol);out.policy_id=pol.id
        out.candidate_sha256=digest(w);out.model_version=p.model_version
        if pol.model_sha256!=out.model_sha256:raise ValueError('Q3 policy model fingerprint mismatch')
        errors=core_problem_errors(p)
        if errors:raise ValueError('Invalid C1 problem: '+'; '.join(f'{x.code}:{x.detail}' for x in errors))
        verify_q3_policy(p,pol)
    except ContextMissing as exc:
        out.status='UNRESOLVED_CONTEXT';out.findings=[str(exc)];return out
    except (ValidationError,ValueError,TypeError,KeyError) as exc:
        out.findings=[f'Q3_POLICY_ERROR: {exc}'];return out
    if w.status not in ('FEASIBLE','OPTIMAL'):
        out.status='INVALID_CANDIDATE';out.findings=['Candidate has no positive scheduling status'];return out
    review=review_core(p,w)
    if review.result!='CANDIDATE_HARD_VALIDATED':
        out.status='INVALID_CANDIDATE';out.hard_validation='FAILED'
        out.findings=[f'{x.code}: {x.detail}' for x in review.findings];return out
    out.hard_validation='PASSED'
    uses=[resolved_use(p,w,a) for a in w.event_assignments]
    by_person_day=defaultdict(list)
    for u in uses:
        for rid in u.resource_ids:by_person_day[(rid,u.day_key)].append(u)
    for v in by_person_day.values():v.sort(key=lambda x:(x.start_minute,x.end_minute,x.event_id))
    components=[]
    legacy=[m for m in pol.metrics if not isinstance(m,(ProtectedIdle,TargetLoadDeviation))]
    if legacy:
        oldpol=QualityPolicy(id=pol.id,model_sha256=digest(p),metrics=legacy)
        old=q1score(p,w,oldpol)
        if old.hard_validation!='PASSED' or old.status not in ('SCORED','INCOMPLETE_SCORING'):
            out.status=old.status;out.findings=old.findings;return out
        by_id={m.metric_id:m for m in old.components}
    else:by_id={}
    for m in pol.metrics:
        if m.id in by_id:
            components.append(by_id[m.id]);continue
        contributions={}
        if isinstance(m, ProtectedIdle):
            per={}
            for b in m.protected_breaks:per.setdefault((b.resource_id,b.day_id),[]).append((b.start_minute,b.end_minute))
            for rid in m.resource_ids:
                for day in p.days:
                    use=by_person_day.get((rid,day.id),[])
                    if len(use)<2:continue
                    penalty=0
                    for left,right in zip(use,use[1:]):
                        if right.start_minute<left.end_minute:
                            out.status='INVALID_CANDIDATE';out.findings=['RESOURCE_OVERLAP during idle scoring'];return out
                        gap=right.start_minute-left.end_minute
                        protected=sum(overlap(left.end_minute,right.start_minute,a,b) for a,b in per.get((rid,day.id),[]))
                        penalty+=gap-protected
                    if penalty:contributions[f'{rid}/{day.id}']=penalty
            units='unprotected idle minutes'
        elif isinstance(m,TargetLoadDeviation):
            for t in m.targets:
                use=by_person_day.get((t.resource_id,t.day_id),[])
                actual=sum(x.work_minutes for x in use)
                difference=abs(actual-t.target_minutes)
                if difference:contributions[f'{t.resource_id}/{t.day_id}']=difference
            units='absolute deviation from explicit daily target minutes'
        else:raise RuntimeError('Q3 type dispatch incomplete')
        raw=sum(contributions.values())
        components.append(QualityComponent(metric_id=m.id,kind=m.kind,tier=m.tier,
                   unit=units,raw_penalty=raw,weight=m.weight,
                   weighted_penalty=raw*m.weight,contributions=dict(sorted(contributions.items()))))
    out.components=components
    out.tier_penalties={tier:sum(m.weighted_penalty for m in components if m.tier==tier) for tier in (2,3,4)}
    out.lexicographic_vector=[out.tier_penalties[t] for t in (2,3,4)]
    out.unscored_soft_rule_ids=[x.id for x in p.constraints if x.enabled and x.strength=='SOFT']
    out.unscored_objective_ids=[x.id for x in p.objectives]
    covered={r for m in pol.metrics if m.kind=='UNMET_SOFT_REQUESTS' for r in m.request_ids}
    out.unscored_soft_request_ids=[x.id for x in p.participation_requests if x.strength=='SOFT' and x.id not in covered]
    out.status='INCOMPLETE_SCORING' if (out.unscored_soft_rule_ids or out.unscored_objective_ids or out.unscored_soft_request_ids) else 'SCORED'
    if out.status!='SCORED':out.findings=['Some requested soft preferences are not represented in policy 0.2.0']
    return out


def compare_v2(left: Q3Score, right: Q3Score) -> Comparison:
    if (left.evaluator_version!='0.2.0' or right.evaluator_version!='0.2.0' or
        left.status!='SCORED' or right.status!='SCORED' or
        left.hard_validation!='PASSED' or right.hard_validation!='PASSED' or
        (left.model_sha256,left.policy_sha256,left.model_version) !=
        (right.model_sha256,right.policy_sha256,right.model_version)):
        return Comparison(status='INCOMPARABLE',reason='Need identical valid Q3 policy and model snapshots')
    a=tuple(left.lexicographic_vector);b=tuple(right.lexicographic_vector)
    return Comparison(status='COMPARABLE',winner='LEFT' if a<b else 'RIGHT' if a>b else 'TIE',left_vector=list(a),right_vector=list(b))
