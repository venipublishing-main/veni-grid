"""Small-school synthetic scale probe, not a 1,500-learner parity benchmark."""
from scripts.build_benchmark_b import build
from veni_grid_contract.conformance import review_core
from veni_grid_quality import score, compare
from veni_grid_quality.policies import benchmark_b_policy as b_policy


def test_b_represented_school_uses_shared_teachers_doubles_and_ten_days():
    p,w=build()
    assert len(p.events)==240 and len(p.resources)==164 and len(p.windows)==70
    assert len(p.days)==10 and len(p.constraints)==40 and len(p.locks)==2
    assert sum(e.duration.count for e in p.events)==248  # eight science doubles
    assert review_core(p,w).result=='CANDIDATE_HARD_VALIDATED'
    r=score(p,w,b_policy(p))
    assert r.status=='SCORED' and r.hard_validation=='PASSED'
    assert len(r.lexicographic_vector)==3 and all(x>=0 for x in r.lexicographic_vector)


def test_b_deliberately_broken_hard_lock_rejected():
    p,w=build();w=w.model_copy(deep=True)
    candidate=next(a for a in w.event_assignments if a.event_id=='event:G00:SCI:D01')
    candidate.start_window_id='window:D02P3'
    assert score(p,w,b_policy(p)).status=='INVALID_CANDIDATE'


def test_b_actual_c1_solver_generates_not_just_verifies():
    from veni_grid_solver import solve
    p,known=build()
    result=solve(p)
    assert result.status=='FEASIBLE' and result.validation=='PASSED'
    assert len(result.candidate.event_assignments)==240
    assert result.quality_optimality=='NOT_ASSESSED' and result.soft_scoring=='NOT_PERFORMED'
    comparison=compare(score(p,known,b_policy(p)),score(p,result.candidate,b_policy(p)))
    assert comparison.status=='COMPARABLE'
    assert comparison.winner in {'LEFT','RIGHT','TIE'}


def test_b_quality_detects_valid_but_inferior_schedule():
    p, known = build()
    worse = known.model_copy(deep=True)
    next(a for a in worse.event_assignments if a.event_id == 'event:G00:MATH:D01').start_window_id = 'window:D01P7'
    assert review_core(p, worse).result == 'CANDIDATE_HARD_VALIDATED'
    good = score(p, known, b_policy(p))
    bad = score(p, worse, b_policy(p))
    assert good.lexicographic_vector == [0,2720,40]
    assert bad.lexicographic_vector == [0,2900,50]
    assert compare(good,bad).winner == 'LEFT'
