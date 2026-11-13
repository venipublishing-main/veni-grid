"""Q2 objective proof and exact independent-score correspondence checks."""
from __future__ import annotations

from copy import deepcopy
import pytest
from quality_tests.test_quality_contract import examples, policy
from veni_grid_quality import score, compare, QualityPolicy, digest
from veni_grid_quality.optimize import optimise
from veni_grid_contract.core_v1 import CoreWitness


def test_multitier_proof_and_nonmutation():
    p,make=examples(); pol=policy(p)
    before=(digest(p), digest(pol))
    baseline=score(p,make(),pol)
    result=optimise(p,pol,{'max_time_seconds':8})
    assert result.status=='FEASIBLE' and result.independent_validation=='PASSED'
    assert result.quality_optimality=='PROVEN' and len(result.stages)==3
    assert all(s.proven_optimal and s.solver_status=='OPTIMAL' for s in result.stages)
    assert result.quality.lexicographic_vector==[0,0,0]
    assert compare(baseline,result.quality).winner=='RIGHT'
    assert result.publication=='NOT_GRANTED'
    assert (digest(p),digest(pol))==before


@pytest.mark.parametrize('kind,details',[
    ('ACTIVITY_DAY_PAIRS',{'tier':2,'weight':10,'activity_ids':['activity:M']}),
    ('RESOURCE_IDLE_MINUTES',{'tier':3,'weight':1,'resource_ids':['person:T']}),
    ('RESOURCE_DAILY_LOAD_SPREAD',{'tier':3,'weight':1,'resource_ids':['person:T'],'day_ids':['day:D1','day:D2']}),
    ('TAGGED_PLACEMENTS',{'tier':4,'weight':4,'event_ids':['event:E1','event:E2'],'tags':['FINAL']}),
    ('RESOURCE_LOCATION_CHANGES',{'tier':3,'weight':20,'resource_ids':['person:T']}),
])
def test_independent_q1_score_equals_compiled_objective(kind,details):
    p,_=examples()
    pol=policy(p,metrics=[{'id':'metric:one','kind':kind,**details}])
    r=optimise(p,pol,{'max_time_seconds':8})
    assert r.status=='FEASIBLE' and r.independent_validation=='PASSED',r.findings
    assert r.quality_optimality=='PROVEN'
    assert r.quality.lexicographic_vector==[0,0,0]
    assert r.quality.model_sha256 == digest(p)
    assert sum(c.weighted_penalty for c in r.quality.components)==0
    assert [s.objective_value for s in r.stages]==[0,0,0]


def with_soft_request():
    p,_=examples();p=p.model_copy(deep=True)
    from veni_grid_contract.models import Activity,Demand,Event,WindowDuration,PlacementDomain,Offering,ParticipationRequest
    p.activities.append(Activity(id='activity:art',label='Art',demand=Demand(basis='PER_ENROLLED',unit='WINDOWS',amount=1)))
    p.events.append(Event(id='event:art',label='Art',activity_id='activity:art',offering_id='offer:art',required=False,
         duration=WindowDuration(count=1),placement=PlacementDomain(start_window_ids=['window:D2P3'])))
    p.offerings.append(Offering(id='offer:art',activity_id='activity:art',event_ids=['event:art'],capacity=1))
    p.participation_requests.append(ParticipationRequest(id='req:art',participant_id='person:student',activity_id='activity:art',
         eligible_offering_ids=['offer:art'],strength='SOFT',min_select=1,max_select=1))
    return p


def test_minimises_unmet_soft_request_count_without_false_hard_claim():
    p=with_soft_request()
    pol=policy(p,metrics=[{'id':'q:unmet','kind':'UNMET_SOFT_REQUESTS','tier':2,'weight':10,'request_ids':['req:art']}])
    r=optimise(p,pol,{'max_time_seconds':10})
    assert r.status=='FEASIBLE' and r.quality_optimality=='PROVEN',r.findings
    assert r.quality.lexicographic_vector==[0,0,0]
    assert any(a.request_id=='req:art' and a.offering_ids==['offer:art'] for a in r.candidate.enrollment_assignments)
    assert any(a.event_id=='event:art' for a in r.candidate.event_assignments)


def test_unscored_soft_policy_is_refused():
    p=with_soft_request();pol=policy(p)
    r=optimise(p,pol)
    assert r.status=='UNSUPPORTED' and r.candidate is None
    assert any('Unscored requirements' in x for x in r.findings)


def test_mismatch_model_policy_is_invalid_input():
    p,_=examples();pol=policy(p).model_copy(deep=True);pol.model_sha256='0'*64
    r=optimise(p,pol)
    assert r.status=='INVALID_INPUT' and r.candidate is None


def test_unknown_under_zero_budget_never_claims_infeasibility():
    p,_=examples();r=optimise(p,policy(p),{'max_time_seconds':0})
    assert r.status=='UNKNOWN' and r.quality_optimality=='NOT_PROVEN' and r.candidate is None


def test_exclusive_only_location_context_refuses_ambiguity():
    p,_=examples();p=p.model_copy(deep=True)
    next(x for x in p.resources if x.id=='space:R2').location_id=None
    r=optimise(p,policy(p))
    assert r.status=='UNSUPPORTED' and r.candidate is None
    assert any('lacks a room location' in x for x in r.findings)


def test_unapproved_repair_mode_is_refused():
    p,_=examples();p=p.model_copy(deep=True)
    p.solve_config.mode='REPAIR'
    r=optimise(p,policy(p))
    assert r.status in ('UNSUPPORTED','INVALID_INPUT') and r.candidate is None


def test_independent_score_disagreement_withholds_candidate(monkeypatch):
    from veni_grid_quality import optimize as q2
    p,_=examples()
    original=q2.score
    def corrupt(problem,candidate,pol):
        report=original(problem,candidate,pol)
        report.tier_penalties[2]+=1
        return report
    monkeypatch.setattr(q2,'score',corrupt)
    r=q2.optimise(p,policy(p))
    assert r.status=='ERROR' and r.candidate is None
    assert any('OBJECTIVE_SCORE_DISAGREEMENT' in x for x in r.findings)


def test_original_c1_solver_does_not_require_quality_policy():
    from veni_grid_solver import solve
    p,_=examples()
    r=solve(p)
    assert r.status=='FEASIBLE' and r.validation=='PASSED'
    assert r.soft_scoring=='NOT_PERFORMED' and r.quality_optimality=='NOT_ASSESSED'
