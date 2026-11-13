"""C3 positive/negative feedback tests, always synthetic and non-publishing."""
import pytest
from scripts.run_c3_probes import fixture
from veni_grid_contract.handoff_common import fingerprint
from veni_grid_contract.option_design import option_errors
from veni_grid_integration.c3_feedback import propose_c3


def test_lab_shortage_replanned_and_actual_c2_rechecked():
    req=fixture();before=fingerprint(req.current.source)
    result=propose_c3(req)
    assert result.previous_c2_status=='INFEASIBLE'
    assert result.status=='PROPOSED_VALIDATED',result.findings
    assert result.preview_c2.status=='FEASIBLE' and result.preview_c2.independent_hard_validation=='PASSED'
    assert result.preview_c2.event_count==2
    assert result.original_still_unchanged and fingerprint(req.current.source)==before
    assert result.acceptance=='NOT_GRANTED' and result.publication=='NOT_GRANTED'
    assert result.other_schedules=='NOT_READ_OR_CHANGED'
    assert len(result.proposed_o1.allocations)==6 and not option_errors(req.current.source.demand,result.proposed_o1)
    byfamily={o.family_id:o.block_id for o in result.proposed_o1.offerings}
    assert len(set(byfamily.values()))==2
    assert all(v=='space:LAB' for v in result.preview_c2.room_assignments.values())
    byevent={a.event_id:a.start_window_id for a in result.preview_c2.candidate.event_assignments}
    assert len(set(byevent.values()))==2


def test_single_available_teacher_cannot_teach_two_concurrent_subjects():
    req=fixture(room_bottleneck=False,teacher_bottleneck=True)
    r=propose_c3(req)
    assert r.previous_c2_status=='INFEASIBLE'
    assert r.status=='PROPOSED_VALIDATED',r.findings
    assert len(set(r.preview_c2.teacher_assignments.values()))==1
    assert r.preview_c2.independent_hard_validation=='PASSED'


def test_if_only_one_block_permitted_the_resource_shortage_is_proved_with_narrow_scope():
    req=fixture(block_limit=1)
    r=propose_c3(req)
    assert r.status=='RESOURCE_RESTRICTED_INFEASIBLE'
    assert r.proof_scope=='RESTRICTED_C3_SINGLE_FAMILY_TEACHING'
    assert r.proposed_o1 is None and r.acceptance=='NOT_GRANTED'


def test_no_schedule_time_separation_means_no_false_proposal():
    req=fixture(allow_different_times=False)
    r=propose_c3(req)
    assert r.status in ('RESOURCE_RESTRICTED_INFEASIBLE','UNKNOWN'),r.findings
    assert r.proposed_o1 is None
    assert r.original_still_unchanged


def test_zero_search_budget_never_claims_global_impossibility():
    req=fixture();req.options.max_time_seconds=0
    r=propose_c3(req)
    assert r.status=='UNKNOWN' and r.proposed_o1 is None


def test_no_extra_domain_must_fail_closed():
    req=fixture();req.proposed_block_windows=req.proposed_block_windows[:1]
    r=propose_c3(req)
    assert r.status in ('RESOURCE_RESTRICTED_INFEASIBLE','UNSUPPORTED')
    assert r.proposed_o1 is None


def test_untrusted_original_snapshot_fails_before_feedback():
    req=fixture();req.current.source_ref.content_sha256='0'*64
    r=propose_c3(req)
    assert r.status=='INVALID_INPUT' and r.proposed_o1 is None


def test_can_return_a_valid_existing_plan_without_rebuilding():
    # Existing successful C2 plan may be tested directly; no new plan should be invented.
    from scripts.run_c2_probes import school_input
    from veni_grid_integration.c3_feedback import C3Input
    current=school_input()
    r=propose_c3(C3Input(current=current,proposed_block_windows=current.target.block_windows))
    assert r.status=='ALREADY_FEASIBLE' and r.proposed_o1 is None
    assert r.original_still_unchanged


def test_flexible_original_plan_explicitly_not_supported_by_first_revision_profile():
    req=fixture()
    # Synthetic source deliberately split an original family: fail closed earlier
    # than a purported repair. Constructing a VALID split is tested in O1; here
    # no unsupported source re-interpretation should be silently accepted.
    req.current.source.plan.offerings[0].block_id='block:B01'
    # source snapshot now stale: must be rejected, not used to derive a guess
    r=propose_c3(req)
    assert r.status=='INVALID_INPUT'


def test_max_families_cap_is_explicit():
    req=fixture();req.options.max_families=1
    r=propose_c3(req)
    assert r.status=='UNSUPPORTED'


def test_proposed_windows_cannot_name_unknown_period():
    req=fixture();req.proposed_block_windows[1].candidate_start_ids=['window:missing']
    r=propose_c3(req)
    assert r.status=='INVALID_INPUT'


def test_rescoring_or_optimising_an_accepted_source_is_not_automatically_done():
    req=fixture();r=propose_c3(req)
    assert r.status=='PROPOSED_VALIDATED'
    assert r.preview_c2.quality_optimisation=='NOT_PERFORMED'
    assert r.preview_c2.publication=='NOT_GRANTED'
    assert r.other_schedules=='NOT_READ_OR_CHANGED'


def test_full_school_shortage_gets_restricted_capacity_bound_not_global_claim():
    from scripts.run_c2_probes import large_school_room_shortage_input
    from veni_grid_integration.c3_feedback import C3Input
    current=large_school_room_shortage_input()
    request=C3Input(current=current,proposed_block_windows=current.target.block_windows,
                    options={'max_families':18,'max_sections':500,'max_time_seconds':2})
    result=propose_c3(request)
    assert result.status=='RESOURCE_RESTRICTED_INFEASIBLE',result.findings
    assert result.proof_scope=='RESTRICTED_C3_SINGLE_FAMILY_TEACHING'
    assert 'at least 12 blocks' in result.findings[0]
    assert result.proposed_o1 is None
    assert result.acceptance=='NOT_GRANTED'


def test_reviewed_section_search_cap_never_mislabels_as_infeasible():
    request=fixture();request.options.max_sections=1
    result=propose_c3(request)
    assert result.status=='UNSUPPORTED',result.findings
    assert result.proof_scope=='NONE'


def test_unproved_preview_cannot_be_discarded_as_impossible(monkeypatch):
    from veni_grid_integration import c3_feedback
    from veni_grid_integration.c2 import C2Result
    request=fixture();original=c3_feedback.solve_c2
    called={'count':0}
    def interrupted(req,*,time_limit_seconds=6):
        called['count']+=1
        if called['count']==1:return original(req,time_limit_seconds=time_limit_seconds)
        return C2Result(status='UNKNOWN',stage='PLACEMENT',findings=['Budget exhausted'],solver_status='UNKNOWN')
    monkeypatch.setattr(c3_feedback,'solve_c2',interrupted)
    result=propose_c3(request)
    assert result.status=='UNKNOWN',result.findings
    assert result.proof_scope=='NONE' and result.proposed_o1 is None
    assert called['count']==2


def test_before_after_card_matches_actual_moved_subject_not_a_static_story(tmp_path):
    import json
    from scripts.render_c3_feedback import render_feedback
    req=fixture();result=propose_c3(req)
    before={o.family_id:o.block_id for o in req.current.source.plan.offerings}
    after={o.family_id:o.block_id for o in result.proposed_o1.offerings}
    report={'original_blocks':before,'proposed_blocks':after}
    rows=render_feedback(report,req,tmp_path)
    assert len(rows)==2
    assert {row['subject'] for row in rows}=={'Subject A','Subject B'}
    assert {row['before'] for row in rows}=={'08:00'}
    assert sorted(row['after'] for row in rows)==['08:00','09:20']
    assert sum(row['moved'] for row in rows)==1
    html=(tmp_path/'c3-feedback-before-after.html').read_text()
    assert html.count('09:20')==1 and 'Approval still required' in html
    assert json.loads((tmp_path/'c3-summary.json').read_text())['plain_english_rows']==rows


def test_human_timetable_report_stays_exactly_tied_to_independent_c2_solution(tmp_path):
    import json
    from pathlib import Path
    from scripts.render_c2_for_people import make_payload,render_html
    src=Path(__file__).resolve().parents[1]/'c2-output'
    p=json.loads((src/'c2-placement-problem.json').read_text())
    w=json.loads((src/'c2-generated-teaching-timetable.json').read_text())
    data=make_payload(p,w)
    assert data['count']==18 and data['sections']==9
    assert len(data['teachers'])==4 and len(data['rooms'])==3
    assert sum(r['double'] for r in data['lesson_records'])==6
    assert {r['day'] for r in data['lesson_records']}=={'day:D1','day:D2'}
    html=render_html(data)
    assert 'Single lesson (1 period)' in html  # Generated card text is derived from each event's actual duration
    assert 'actual generated teaching schedule' in html
    assert 'school_context' in html


def test_invalid_generated_timetable_cannot_be_rendered_as_valid(tmp_path):
    import json
    from pathlib import Path
    from scripts.render_c2_for_people import make_payload
    root=Path(__file__).resolve().parents[1]/'c2-output'
    p=json.loads((root/'c2-placement-problem.json').read_text())
    w=json.loads((root/'c2-generated-teaching-timetable.json').read_text())
    w['event_assignments'][0]['start_window_id']='window:UNKNOWN'
    with pytest.raises(ValueError):make_payload(p,w)
