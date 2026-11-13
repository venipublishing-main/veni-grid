"""C4 flexible multi-occurrence planning, independent proof/approval boundaries."""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
from pathlib import Path
import json
import pytest

from scripts.run_c4_probes import crossed_multi_occurrence_fixture
from scripts.run_c2_probes import school_input
from scripts.run_c3_probes import fixture as c3_fixture
from veni_grid_integration.c2 import C2Result,solve_c2
from veni_grid_integration.c4_flexible_feedback import C4Input,propose_c4,review_errors
from veni_grid_contract.handoff_common import fingerprint
from veni_grid_contract.option_design import option_errors
from veni_grid_contract.conformance import review_core
from scripts.render_c4_review import render


def test_crossed_and_multi_occurrence_generates_genuinely_teachable_resectioning():
    req=crossed_multi_occurrence_fixture()
    src_before=fingerprint(req.current.source)
    current=solve_c2(req.current,time_limit_seconds=8)
    assert current.status=='INFEASIBLE' and current.proof_scope=='FIXED_O1_C2'
    result=propose_c4(req)
    assert result.status=='PROPOSED_VALIDATED',result.findings
    assert result.review and result.preview_c2
    assert result.review.preserved_compulsory_requests==48
    assert result.review.after_section_count==9
    assert result.review.before_section_count==10
    assert len(result.review.changed_request_ids)==18
    assert result.preview_c2.event_count==18
    assert len(result.preview_c2.teacher_assignments)==18
    assert len(result.preview_c2.room_assignments)==18
    assert result.preview_c2.independent_hard_validation=='PASSED'
    assert review_core(result.preview_c2.placement_problem,result.preview_c2.candidate).result=='CANDIDATE_HARD_VALIDATED'
    assert option_errors(req.current.source.demand,result.proposed_o1)==[]
    assert result.source_unchanged and fingerprint(req.current.source)==src_before
    assert result.acceptance=='NOT_GRANTED' and result.publication=='NOT_GRANTED'
    assert result.other_schedules=='NOT_READ_OR_CHANGED'
    assert result.review.authority=='SIMULATED_IN_MEMORY_ONLY'
    assert result.review.approval=='REQUIRES_AUTHENTICATED_REVIEW'
    assert result.review.saved=='NO'
    assert review_errors(req.current,result.proposed_o1,result.preview_c2,result.review)==[]
    # The benchmark uses two occurrences per section; D is a lab double on each day.
    d={o.block_id for o in result.proposed_o1.offerings if o.family_id=='family:D'}
    assert len(d)>=2
    d_e=[e for e in result.preview_c2.placement_problem.events if 'Subject D' in e.label]
    assert all(e.duration.count==2 for e in d_e)


def test_source_fingerprint_and_draft_comparison_cannot_be_forged():
    req=crossed_multi_occurrence_fixture();r=propose_c4(req)
    altered=r.review.model_copy(deep=True)
    altered.changed_request_ids=[]
    assert review_errors(req.current,r.proposed_o1,r.preview_c2,altered)==['REVIEW_CONTENT_MISMATCH']
    altered=r.review.model_copy(deep=True);altered.source_sha256='0'*64
    assert 'REVIEW_CONTENT_MISMATCH' in review_errors(req.current,r.proposed_o1,r.preview_c2,altered)


def test_draft_does_not_change_o1_source_or_external_timelines():
    req=crossed_multi_occurrence_fixture();snapshot=req.model_dump_json()
    r=propose_c4(req)
    assert req.model_dump_json()==snapshot
    assert r.preview_c2.organisation_wide_clashes=='NOT_ASSESSED'
    assert r.preview_c2.publication=='NOT_GRANTED'


def test_original_already_teachable_does_not_invent_alternative():
    req=school_input()
    value=C4Input(current=req,proposed_block_windows=req.target.block_windows)
    r=propose_c4(value)
    assert r.status=='ALREADY_FEASIBLE' and r.proposed_o1 is None and r.review is None


def test_zero_search_time_does_not_become_a_false_impossibility():
    req=crossed_multi_occurrence_fixture();req.options.max_time_seconds=0
    r=propose_c4(req)
    assert r.status=='UNKNOWN' and r.proof_scope=='NONE' and r.review is None


def test_stale_source_refusal_before_feedback():
    req=crossed_multi_occurrence_fixture();req.current.source_ref.content_sha256='0'*64
    r=propose_c4(req)
    assert r.status=='INVALID_INPUT' and r.proposed_o1 is None


def test_proposed_time_domains_cannot_invent_windows():
    req=crossed_multi_occurrence_fixture();req.proposed_block_windows[0].candidate_start_ids=['window:absent']
    r=propose_c4(req)
    assert r.status=='INVALID_INPUT' and r.review is None


def test_missing_required_occurrence_domains_fail_closed():
    req=crossed_multi_occurrence_fixture()
    req.proposed_block_windows=[b for b in req.proposed_block_windows if b.occurrence_key=='occ:D1']
    r=propose_c4(req)
    assert r.status=='UNSUPPORTED' and r.proposed_o1 is None


def test_review_maximum_input_limits_are_explicit_not_proved_impossible():
    req=crossed_multi_occurrence_fixture();req.options.max_requests=40
    r=propose_c4(req)
    assert r.status=='UNSUPPORTED' and r.proof_scope=='NONE'


def test_limited_candidates_never_forces_unproved_global_infeasibility(monkeypatch):
    from veni_grid_integration import c4_flexible_feedback as c4
    req=crossed_multi_occurrence_fixture();req.options.max_candidates=1
    original=c4.solve_c2;calls={'count':0}
    def override(*args,**kwargs):
        calls['count']+=1
        if calls['count']==1:return original(*args,**kwargs)
        return C2Result(status='UNKNOWN',stage='PLACEMENT',solver_status='UNKNOWN',
                        findings=['Synthetic interrupted placement'])
    monkeypatch.setattr(c4,'solve_c2',override)
    r=c4.propose_c4(req)
    assert calls['count']==2
    assert r.status=='UNKNOWN' and r.proof_scope=='NONE' and r.proposed_o1 is None


def test_proved_fixed_plan_exclusion_does_not_delete_all_alternatives(monkeypatch):
    from veni_grid_integration import c4_flexible_feedback as c4
    req=crossed_multi_occurrence_fixture();original=c4.solve_c2;calls={'count':0}
    def override(*args,**kwargs):
        calls['count']+=1
        if calls['count']==2:return C2Result(status='INFEASIBLE',stage='PLACEMENT',
                  solver_status='INFEASIBLE',proof_scope='FIXED_O1_C2',findings=['Synthetic proven clash'])
        return original(*args,**kwargs)
    monkeypatch.setattr(c4,'solve_c2',override)
    r=c4.propose_c4(req)
    assert calls['count']>=3
    assert r.status=='PROPOSED_VALIDATED',r.findings
    assert r.candidate_attempts>=2
    assert r.review and r.preview_c2.independent_hard_validation=='PASSED'


def test_only_one_block_and_one_lab_returns_restricted_proof():
    tiny=c3_fixture(block_limit=1)
    req=C4Input(current=tiny.current,proposed_block_windows=tiny.proposed_block_windows)
    r=propose_c4(req)
    assert r.status=='RESOURCE_RESTRICTED_INFEASIBLE',r.findings
    assert r.proof_scope=='RESTRICTED_C4_FLEXIBLE_TEACHING'
    assert r.review is None and r.publication=='NOT_GRANTED'


def test_no_qualified_staff_returns_restricted_supply_result():
    req=crossed_multi_occurrence_fixture()
    req.current.target.credentials=[c for c in req.current.target.credentials if c.resource_id!='person:TD']
    r=propose_c4(req)
    assert r.status=='RESOURCE_RESTRICTED_INFEASIBLE'
    assert r.proof_scope=='RESTRICTED_C4_FLEXIBLE_TEACHING'


def test_expiring_credentials_are_not_guessed_on_abstract_calendar():
    from veni_grid_contract.primitives import Interval
    from datetime import datetime,timezone
    req=crossed_multi_occurrence_fixture()
    req.current.target.credentials[0].valid_during=Interval(
        start=datetime(2026,1,1,tzinfo=timezone.utc),end=datetime(2027,1,1,tzinfo=timezone.utc))
    r=propose_c4(req)
    assert r.status=='UNSUPPORTED'


def test_family_section_bounds_are_verified_independently():
    req=crossed_multi_occurrence_fixture()
    r=propose_c4(req)
    catalog={f.id:f for f in req.current.source.demand.families}
    bysection=Counter(a.offering_id for a in r.proposed_o1.allocations)
    for o in r.proposed_o1.offerings:
        f=catalog[o.family_id]
        assert f.min_members<=bysection[o.id]<=f.max_members


def test_tampered_candidate_timetable_cannot_receive_valid_review():
    req=crossed_multi_occurrence_fixture();r=propose_c4(req)
    preview=r.preview_c2.model_copy(deep=True)
    preview.candidate.event_assignments[0].start_window_id='window:NOT-REAL'
    assert 'INDEPENDENT_PLACEMENT_CHECK_FAILED' in review_errors(req.current,r.proposed_o1,preview,r.review)


def test_renderer_uses_real_18_events_and_keeps_approval_disabled(tmp_path):
    from scripts.render_c4_review import render
    req=crossed_multi_occurrence_fixture();r=propose_c4(req)
    payload=render(req,r,tmp_path)
    assert payload['kind']=='ACTUAL_VALIDATED_C2_CANDIDATE'
    assert payload['count']==18 and payload['sections']==9
    assert len(payload['teachers'])==4 and len(payload['rooms'])==3
    html=(tmp_path/'c4-review-before-after.html').read_text()
    assert '18</strong>' in html and '48</strong>' in html
    assert 'secure service required' in html.lower()
    assert 'data-teacher=' in html and 'data-room=' in html
    assert 'Not enough suitably qualified teachers' in html
    assert 'teacher' in (tmp_path/'c4-proposed-teaching-timetable.html').read_text().lower()
    assert json.loads((tmp_path/'c4-review-receipt.json').read_text())['approval']=='REQUIRES_AUTHENTICATED_REVIEW'


def test_invalid_preview_is_never_rendered_as_valid(tmp_path):
    from scripts.render_c4_review import render
    req=crossed_multi_occurrence_fixture();r=propose_c4(req)
    r.review.proposed_o1_sha256='0'*64
    with pytest.raises(ValueError):render(req,r,tmp_path)


def test_different_policy_or_schedule_authority_is_never_assumed():
    req=crossed_multi_occurrence_fixture();r=propose_c4(req)
    assert r.acceptance=='NOT_GRANTED' and r.publication=='NOT_GRANTED'
    assert r.review.authority=='SIMULATED_IN_MEMORY_ONLY'
    assert r.other_schedules=='NOT_READ_OR_CHANGED'
    assert r.proof_scope=='NONE'


def test_no_unsupported_soft_rules_are_silently_ignored():
    from veni_grid_contract.models import ActivitySpread,RuleSource,RuleStrength
    req=crossed_multi_occurrence_fixture()
    req.current.target.constraints.append(ActivitySpread(id='rule:soft:dummy',
        source=RuleSource.USER,strength=RuleStrength.SOFT,
        activity_ids=['activity:missing'],minimum_distinct_days=2))
    r=propose_c4(req)
    assert r.status=='UNSUPPORTED' and r.review is None


def test_computational_section_cap_never_claims_school_infeasibility():
    req=crossed_multi_occurrence_fixture();req.options.max_sections=2
    r=propose_c4(req)
    assert r.status=='UNSUPPORTED' and r.proof_scope=='NONE'
