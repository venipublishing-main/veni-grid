"""Q3 versioned break and targeted staff-load semantics; hand-calculated oracles."""
from copy import deepcopy
import pytest
from quality_tests.test_quality_contract import examples, policy as old_policy
from veni_grid_quality import score as score_q1, digest
from veni_grid_quality.q3_policy import QualityPolicyV2, ProtectedIdle,TargetLoadDeviation
from veni_grid_quality.q3_score import score_v2, compare_v2
from veni_grid_quality.q3_optimize import optimise_v2


def q3(p,metrics):return QualityPolicyV2(id='policy:q3',model_sha256=digest(p),metrics=metrics)

def break_metric(spans=None):
    return ProtectedIdle(id='metric:protected',tier=2,weight=1,resource_ids=['person:T'],
          protected_breaks=[{'resource_id':'person:T','day_id':'day:D1','start_minute':a,'end_minute':b}
                            for a,b in (spans or [])])

def target_metric(days=None):
    if days is None:days=[('day:D1',80),('day:D2',0)]
    return TargetLoadDeviation(id='metric:targets',tier=3,weight=1,
          targets=[{'resource_id':'person:T','day_id':day,'target_minutes':target}
                   for day,target in days])


def test_break_versus_legacy_gap_hand_calculation():
    p,w=examples();w=w()
    assert score_q1(p,w,old_policy(p)).components[1].raw_penalty==40
    assert score_v2(p,w,q3(p,[break_metric([(520,540)])])).components[0].raw_penalty==20
    assert score_v2(p,w,q3(p,[break_metric([(520,560)])])).components[0].raw_penalty==0
    assert score_v2(p,w,q3(p,[break_metric([(530,540)])])).components[0].raw_penalty==30


def test_protected_break_does_not_subtract_time_when_working():
    p,w=examples()
    # Both lessons adjacent, and protected interval is occupied by the second lesson.
    candidate=w('window:D1P2','space:R1')
    a=score_v2(p,candidate,q3(p,[break_metric([(520,560)])]))
    assert a.status=='SCORED' and a.lexicographic_vector==[0,0,0]


def test_multiple_disjoint_breaks_not_double_counted():
    p,w=examples()
    result=score_v2(p,w(),q3(p,[break_metric([(520,530),(540,550)])]))
    assert result.lexicographic_vector==[20,0,0]


def test_staff_load_targets_count_work_not_elapsed_breaks():
    p,w=examples()
    r=score_v2(p,w(),q3(p,[target_metric([('day:D1',80),('day:D2',0)])]))
    assert r.status=='SCORED' and r.lexicographic_vector==[0,0,0]
    off=score_v2(p,w('window:D2P1'),q3(p,[target_metric([('day:D1',80),('day:D2',0)])]))
    # 40 instead of 80 on day one; 40 instead of 0 on off day.
    assert off.lexicographic_vector==[0,80,0]


def test_part_time_day_scope_is_explicit():
    p,w=examples()
    r=score_v2(p,w('window:D2P1'),q3(p,[target_metric([('day:D1',40)])]))
    assert r.status=='SCORED' and r.lexicographic_vector==[0,0,0]


def test_same_candidate_is_different_under_two_policies_and_incomparable():
    p,w=examples()
    a=score_v2(p,w(),q3(p,[break_metric([(520,560)])]))
    b=score_v2(p,w(),q3(p,[break_metric([(520,540)])]))
    assert compare_v2(a,b).status=='INCOMPARABLE'
    assert a.evaluator_version=='0.2.0'

@pytest.mark.parametrize('case',['overlap','bad_span','duplicate_target','duplicate_metric'])
def test_bad_interval_duplicate_metric_or_target_fails_closed(case):
    p,_=examples()
    with pytest.raises(ValueError):
        if case=='overlap': q3(p,[break_metric([(520,540),(530,550)])])
        elif case=='bad_span': break_metric([(560,520)])
        elif case=='duplicate_target': q3(p,[target_metric([('day:D1',40),('day:D1',80)])])
        else: q3(p,[break_metric([]),break_metric([])])


def test_wrong_person_or_day_fails_closed():
    p,w=examples()
    wrong=break_metric([(520,540)]).model_copy(deep=True)
    wrong.resource_ids=['space:R1']; wrong.protected_breaks[0].resource_id='space:R1'
    assert score_v2(p,w(),q3(p,[wrong])).status=='INVALID_INPUT'
    bad=target_metric();bad.targets[0].day_id='day:UNKNOWN'
    assert score_v2(p,w(),q3(p,[bad])).status=='INVALID_INPUT'


def test_versioned_policy_cannot_be_passed_to_q1_scorer():
    p,w=examples()
    q=q3(p,[break_metric([(520,560)])])
    assert score_q1(p,w(),q.model_dump(mode='json')).status=='INVALID_INPUT'


def test_v2_optimiser_proves_exact_short_example():
    p,w=examples()
    pol=q3(p,[break_metric([(520,540)]),target_metric()])
    result=optimise_v2(p,pol,{'max_time_seconds':7})
    assert result.status=='FEASIBLE',result.findings
    assert result.independent_validation=='PASSED'
    assert result.quality.status=='SCORED'
    assert result.quality_optimality=='PROVEN'
    assert result.quality.lexicographic_vector==[0,0,0]
    assert compare_v2(score_v2(p,w(),pol),result.quality).winner=='RIGHT'
    assert result.publication=='NOT_GRANTED'


def test_v2_optimiser_respects_both_new_metric_oracles():
    p,w=examples()
    # Make all variants legal and constrain both penalties to be nonzero or zero correctly.
    pol=q3(p,[break_metric([(520,540)]),target_metric([('day:D1',80),('day:D2',0)])])
    r=optimise_v2(p,pol,{'max_time_seconds':7})
    assert r.status=='FEASIBLE' and r.quality_optimality=='PROVEN'
    assert r.stages[0].objective_value==r.quality.tier_penalties[2]
    assert r.stages[1].objective_value==r.quality.tier_penalties[3]


def test_break_metric_rejects_dated_input_without_guessing_timezone():
    from datetime import date
    p,w=examples();p=p.model_copy(deep=True)
    p.days[0].date=date(2026,11,16);p.days[1].date=date(2026,11,17)
    r=score_v2(p,w(),q3(p,[break_metric([(520,540)])]))
    assert r.status=='UNRESOLVED_CONTEXT'
    o=optimise_v2(p,q3(p,[break_metric([(520,540)])]))
    assert o.status=='UNSUPPORTED'


def test_empty_search_budget_unknown():
    p,_=examples();r=optimise_v2(p,q3(p,[target_metric()]),{'max_time_seconds':0})
    assert r.status=='UNKNOWN' and r.candidate is None and r.quality_optimality=='NOT_PROVEN'


def test_stale_policy_refused_and_no_c1_mutation():
    p,w=examples();before=digest(p)
    pol=q3(p,[target_metric()]).model_copy(deep=True);pol.model_sha256='0'*64
    assert optimise_v2(p,pol).status=='INVALID_INPUT'
    assert digest(p)==before
    from veni_grid_solver import solve
    r=solve(p)
    assert r.status=='FEASIBLE' and r.validation=='PASSED'


def test_q3_can_mix_original_metric_without_rewriting_it():
    p,w=examples();orig=old_policy(p).metrics[0]
    pol=q3(p,[orig,break_metric([(520,560)]),target_metric()])
    result=score_v2(p,w(),pol)
    assert result.status=='SCORED' and result.lexicographic_vector==[10,0,0]
    optimized=optimise_v2(p,pol,{'max_time_seconds':7})
    assert optimized.status=='FEASIBLE' and optimized.quality_optimality=='PROVEN'
    assert optimized.quality.lexicographic_vector==[0,80,0]  # tier-2 subject spread outranks part-time targets


def test_unscored_soft_rules_refused():
    p,_=examples();p=p.model_copy(deep=True)
    from veni_grid_contract.models import ActivitySpread
    p.constraints.append(ActivitySpread(id='rule:prefer',source='USER',strength='SOFT',activity_ids=['activity:M'],minimum_distinct_days=2))
    pol=q3(p,[target_metric()])
    assert score_v2(p,examples()[1](),pol).status in ('INVALID_CANDIDATE','INCOMPLETE_SCORING')
    assert optimise_v2(p,pol).status=='UNSUPPORTED'
