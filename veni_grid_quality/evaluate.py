"""Deterministic, solver-independent Q1 candidate quality measurement.

All raw penalties are nonnegative integer quantities. Results are comparable
only for the identical canonical problem and policy, and only when fully scored.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import timezone
import hashlib
import json
from pydantic import ValidationError
from veni_grid_contract.core_v1 import CoreProblem, CoreWitness, resolved_use
from veni_grid_contract.conformance import review_core
from veni_grid_contract.models import ResourceKind
from veni_grid_contract.validation import window_placement
from .models import (QualityPolicy, QualityResult, QualityComponent, Comparison,
                     ActivityPairs, ResourceIdle, DailySpread, TaggedPlacement,
                     LocationChanges, UnmetRequests)


class ContextMissing(ValueError):
    pass


def digest(value) -> str:
    data = value.model_dump(mode='json') if hasattr(value, 'model_dump') else value
    text = json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def verify_policy(problem: CoreProblem, policy: QualityPolicy):
    resources = {r.id for r in problem.resources}
    persons = {r.id for r in problem.resources if r.kind == ResourceKind.PERSON}
    activities = {a.id for a in problem.activities}
    events = {e.id for e in problem.events}
    requests = {q.id: q for q in problem.participation_requests}
    days = {d.id for d in problem.days}
    for metric in policy.metrics:
        for field, allowed in [('resource_ids', resources), ('activity_ids', activities),
                               ('event_ids', events), ('day_ids', days), ('request_ids', requests)]:
            values = getattr(metric, field, None)
            if values is not None:
                if len(set(values)) != len(values):
                    raise ValueError(f'{metric.id}: duplicate {field}')
                missing = set(values) - set(allowed)
                if missing: raise ValueError(f'{metric.id}: unknown {field}: {sorted(missing)}')
        if isinstance(metric, (ResourceIdle, LocationChanges, DailySpread)):
            if not set(metric.resource_ids) <= persons:
                raise ValueError(f'{metric.id}: Q1 resource metric currently supports PERSON only')
        if isinstance(metric, UnmetRequests):
            if any(requests[rid].strength != 'SOFT' for rid in metric.request_ids):
                raise ValueError(f'{metric.id}: only SOFT participation requests may be scored here')
        if isinstance(metric, TaggedPlacement) and (len(set(metric.tags)) != len(metric.tags) or any(not t for t in metric.tags)):
            raise ValueError(f'{metric.id}: tags must be nonempty and unique')


def score(problem: CoreProblem | dict, witness: CoreWitness | dict, policy: QualityPolicy | dict) -> QualityResult:
    out = QualityResult(status='INVALID_INPUT')
    try:
        p = (CoreProblem.model_validate_json(json.dumps(problem, allow_nan=False), strict=True)
             if isinstance(problem, dict) else CoreProblem.model_validate(problem.model_dump(mode='json')))
        w = (CoreWitness.model_validate_json(json.dumps(witness, allow_nan=False), strict=True)
             if isinstance(witness, dict) else CoreWitness.model_validate(witness.model_dump(mode='json')))
        pol = (QualityPolicy.model_validate_json(json.dumps(policy, allow_nan=False), strict=True)
               if isinstance(policy, dict) else QualityPolicy.model_validate(policy.model_dump(mode='json')))
        out.policy_id = pol.id; out.policy_sha256 = digest(pol)
        out.model_sha256 = digest(p); out.model_version = p.model_version
        out.candidate_sha256 = digest(w)
        if out.model_sha256 != pol.model_sha256:
            raise ValueError('Policy is pinned to a different problem snapshot')
        verify_policy(p, pol)
    except (ValidationError, ValueError, TypeError) as exc:
        out.findings = [f'QUALITY_INPUT_ERROR: {exc}']; return out
    if w.status not in ('FEASIBLE', 'OPTIMAL'):
        out.status = 'INVALID_CANDIDATE'; out.findings = ['Cannot score a non-candidate solver status']; return out
    review = review_core(p, w)
    if review.result != 'CANDIDATE_HARD_VALIDATED':
        out.status = 'INVALID_INPUT' if review.result == 'INVALID_INPUT' else 'INVALID_CANDIDATE'
        out.hard_validation = 'NOT_RUN' if review.result == 'INVALID_INPUT' else 'FAILED'
        out.findings = [f'{f.code}: {f.detail}' for f in review.findings]
        return out
    out.hard_validation = 'PASSED'
    uses = [resolved_use(p, w, a) for a in w.event_assignments]
    windows = {window.id: window for window in p.windows}
    events = {event.id: event for event in p.events}
    requests = {request.id: request for request in p.participation_requests}
    assigned = {a.event_id:a for a in w.event_assignments}
    enrolled = {e.request_id: len(e.offering_ids) for e in w.enrollment_assignments}
    by_resource_day = defaultdict(list)
    for u in uses:
        for resource_id in u.resource_ids:
            by_resource_day[(resource_id, u.day_key)].append(u)
    for key in by_resource_day:
        by_resource_day[key].sort(key=lambda u: (u.start_minute, u.end_minute, u.event_id))
    components = []
    try:
        for m in pol.metrics:
            c = Counter()
            unit='count'
            if isinstance(m, ActivityPairs):
                counts = Counter((events[u.event_id].activity_id, u.day_key) for u in uses
                                 if events[u.event_id].activity_id in m.activity_ids)
                for (aid, day_id), n in sorted(counts.items()):
                    if n > 1: c[f'{aid}/{day_id}'] += n*(n-1)//2
                unit='same-day event pairs'
            elif isinstance(m, ResourceIdle):
                for (rid, day_id), group in sorted(by_resource_day.items()):
                    if rid not in m.resource_ids: continue
                    for left, right in zip(group, group[1:]):
                        if left.interval and right.interval:
                            idle = max(0, int((right.interval.start.astimezone(timezone.utc) -
                                                   left.interval.end.astimezone(timezone.utc)).total_seconds() // 60))
                        else:
                            idle = max(0, right.start_minute - left.end_minute)
                        if idle: c[f'{rid}/{day_id}'] += idle
                unit='elapsed idle minutes, including breaks'
            elif isinstance(m, DailySpread):
                for rid in m.resource_ids:
                    daily = [sum(u.work_minutes for u in by_resource_day.get((rid,day), [])) for day in m.day_ids]
                    spread = max(daily)-min(daily)
                    if spread: c[rid] = spread
                unit='daily workload minute spread'
            elif isinstance(m, TaggedPlacement):
                tags = set(m.tags)
                for u in uses:
                    if u.event_id not in m.event_ids: continue
                    selected_bell = windows[assigned[u.event_id].start_window_id].bell_id
                    if any(tags.intersection(win.tags) and win.day_id == u.day_key and
                           win.bell_id == selected_bell and
                           win.start_minute < u.end_minute and u.start_minute < win.end_minute
                           for win in p.windows):
                        c[u.event_id] += 1
                unit='events occupying tagged windows'
            elif isinstance(m, LocationChanges):
                for (rid, day), group in sorted(by_resource_day.items()):
                    if rid not in m.resource_ids: continue
                    if any(u.location_id is None for u in group):
                        raise ContextMissing(f'{m.id}: location missing for {rid}/{day}')
                    for left, right in zip(group, group[1:]):
                        if left.location_id != right.location_id:
                            c[f'{rid}/{day}'] += 1
                unit='person location changes'
            elif isinstance(m, UnmetRequests):
                for rid in m.request_ids:
                    missing = max(0, requests[rid].min_select - enrolled.get(rid, 0))
                    if missing: c[rid] = missing
                unit='unmet soft requested selections'
            raw = sum(c.values())
            components.append(QualityComponent(metric_id=m.id, kind=m.kind, tier=m.tier,
                        unit=unit, raw_penalty=raw, weight=m.weight,
                        weighted_penalty=raw*m.weight, contributions=dict(sorted(c.items()))))
    except ContextMissing as exc:
        out.status = 'UNRESOLVED_CONTEXT'; out.findings = [str(exc)]; return out
    out.components = components
    out.tier_penalties = {tier:sum(c.weighted_penalty for c in components if c.tier==tier) for tier in (2,3,4)}
    out.lexicographic_vector = [out.tier_penalties[tier] for tier in (2,3,4)]
    out.unscored_soft_rule_ids = [r.id for r in p.constraints if r.enabled and r.strength == 'SOFT']
    out.unscored_objective_ids = [o.id for o in p.objectives]
    represented = {rid for m in pol.metrics if isinstance(m, UnmetRequests) for rid in m.request_ids}
    out.unscored_soft_request_ids = [q.id for q in p.participation_requests if q.strength == 'SOFT' and q.id not in represented]
    if any((out.unscored_soft_rule_ids, out.unscored_objective_ids, out.unscored_soft_request_ids)):
        out.status = 'INCOMPLETE_SCORING'
        out.findings.append('Some existing soft rules/objectives/requests are not covered by this explicit quality policy')
    else:
        out.status = 'SCORED'
    return out


def compare(left: QualityResult, right: QualityResult) -> Comparison:
    if left.status != 'SCORED' or right.status != 'SCORED':
        return Comparison(status='INCOMPARABLE', reason='Both results must be completely scored')
    if left.hard_validation != 'PASSED' or right.hard_validation != 'PASSED':
        return Comparison(status='INCOMPARABLE', reason='Independent hard validation must pass for both')
    if (left.model_sha256, left.model_version, left.policy_sha256) != (right.model_sha256, right.model_version, right.policy_sha256):
        return Comparison(status='INCOMPARABLE', reason='Different problem versions or quality policies')
    first = tuple(left.lexicographic_vector); second = tuple(right.lexicographic_vector)
    return Comparison(status='COMPARABLE', winner='LEFT' if first<second else 'RIGHT' if first>second else 'TIE',
                      left_vector=list(first), right_vector=list(second))
