from __future__ import annotations
import copy
import json
from datetime import date, timedelta, timezone
from pathlib import Path
import pytest
from pydantic import ValidationError
from jsonschema import Draft202012Validator, FormatChecker

from veni_grid_contract.handoff_common import (HandoffError,SnapshotRef,fingerprint,
    snapshot_ref,stable_id,freshness_errors)
from veni_grid_contract.options_handoff import (OptionsHandoff,LessonHandoffResult,
    build_lesson_handoff,lesson_handoff_errors)
from veni_grid_contract.placement_v04 import PlacementWitness,placement_witness_errors
from veni_grid_contract.exam_handoff import (ExamHandoff,ExamHandoffResult,
    build_exam_handoff,exam_handoff_errors,session_id)
from veni_grid_contract.coverage import CoverageWitness,coverage_errors
from veni_grid_contract.handoff_changes import (StaffingReviewRequest,StaffingReviewResult,
    review_staffing_change,derive_changes)
from veni_grid_contract.placement_claims import derive_dated_placement_claims

ROOT=Path(__file__).resolve().parents[1]

def load(folder,name):return json.loads((ROOT/'fixtures_v04'/folder/name).read_text())

def options():
    return OptionsHandoff.model_validate(load('H1_options_to_lessons','request.json'))

def lessons():
    return LessonHandoffResult.model_validate(load('H1_options_to_lessons','handoff.json'))

def lesson_witness():
    return PlacementWitness.model_validate(load('H1_options_to_lessons','placement-witness.json'))

def exams(origin='GRID'):
    folder='H2_grid_exams_to_coverage' if origin=='GRID' else 'H3_manual_exams_to_coverage'
    return ExamHandoff.model_validate(load(folder,'request.json'))

def exam_result():
    return ExamHandoffResult.model_validate(load('H2_grid_exams_to_coverage','handoff.json'))

def changes():
    r=StaffingReviewRequest.model_validate(load('H4_staffing_only_change','review-request.json'))
    cur=[SnapshotRef.model_validate(x) for x in load('H4_staffing_only_change','authoritative-current-refs.json')]
    return r,cur

def codes(errors):return {e.code for e in errors}

def repin(req):
    req.source_ref.content_sha256=fingerprint(req.source)
    return req

def rebuilt_output_digest(result):
    result.receipt.output_sha256=fingerprint(result.problem)
    return result


def test_options_handoff_preserves_all_sections_requests_and_patterns():
    r=lessons()
    assert not lesson_handoff_errors(r)
    assert len(r.problem.offerings)==4
    assert len(r.problem.participation_requests)==12
    assert len(r.problem.events)==8
    assert sum(e.duration.count for e in r.problem.events)==12
    assert not placement_witness_errors(r.problem,lesson_witness())
    assert r.receipt.readiness=='INPUT_VALIDATED_NOT_SOLVED'


def test_option_transfer_does_not_mutate_source_or_config():
    r=options();before=r.model_dump_json();out=build_lesson_handoff(r)
    assert r.model_dump_json()==before
    original=out.request.target.windows[0].start_minute
    out.problem.windows[0].start_minute+=1
    assert out.request.target.windows[0].start_minute==original


def test_repeating_transfer_is_deterministic_but_does_not_claim_database_idempotency():
    r=options()
    assert build_lesson_handoff(r).model_dump_json()==build_lesson_handoff(r).model_dump_json()


def test_new_source_revision_keeps_entity_ids_but_changes_receipt_identity():
    r=options();old=build_lesson_handoff(r)
    r.source_ref.revision+=1
    new=build_lesson_handoff(r)
    assert [e.id for e in old.problem.events]==[e.id for e in new.problem.events]
    assert old.receipt.handoff_id!=new.receipt.handoff_id


def test_target_namespace_separates_two_uses_of_same_option_plan():
    r=options();a=build_lesson_handoff(r)
    r.target.schedule_id='schedule:another-year';b=build_lesson_handoff(r)
    assert not {e.id for e in a.problem.events}&{e.id for e in b.problem.events}


@pytest.mark.parametrize('state',['DRAFT','RETIRED'])
def test_unaccepted_sources_are_not_implicitly_accepted(state):
    r=options();r.source_ref.state=state
    with pytest.raises(HandoffError,match='SOURCE_NOT_ACCEPTED'):build_lesson_handoff(r)


def test_changed_source_content_cannot_reuse_old_fingerprint():
    r=options();r.source.demand.families[0].label='Altered label'
    with pytest.raises(HandoffError,match='SOURCE_CONTENT_MISMATCH'):build_lesson_handoff(r)


def test_wrong_organisation_rejected():
    r=options();r.target.organisation_id='org:other'
    with pytest.raises(HandoffError,match='CROSS_ORGANISATION_SOURCE'):build_lesson_handoff(r)


def test_source_cannot_be_writable_target():
    r=options();r.target.schedule_id=r.source_ref.schedule_id
    with pytest.raises(HandoffError,match='SOURCE_IS_TARGET'):build_lesson_handoff(r)


def test_unfulfilled_accepted_choice_plan_rejected_after_rehash():
    r=options();r.source.plan.allocations.pop();repin(r)
    with pytest.raises(HandoffError,match='INVALID_ACCEPTED_OPTION_PLAN'):build_lesson_handoff(r)


def test_missing_curriculum_not_guessed():
    r=options();r.target.templates.pop()
    with pytest.raises(HandoffError,match='CURRICULUM_MAPPING_INCOMPLETE'):build_lesson_handoff(r)


def test_lesson_totals_must_match_explicit_curriculum():
    r=options();r.target.templates[0].required_units=5
    with pytest.raises(ValidationError,match='curriculum demand'):build_lesson_handoff(r)


def test_missing_learner_identity_is_not_matched_by_display_name():
    r=options();r.target.resources=[x for x in r.target.resources if x.id!=r.source.demand.participant_ids[0]]
    with pytest.raises(HandoffError,match='LEARNER_IDENTITY_UNRESOLVED'):build_lesson_handoff(r)


def test_missing_block_binding_rejected():
    r=options();r.target.bindings.pop()
    with pytest.raises(HandoffError,match='BLOCK_BINDING_INCOMPLETE'):build_lesson_handoff(r)


def test_duplicate_block_binding_rejected():
    r=options();r.target.bindings.append(copy.deepcopy(r.target.bindings[0]))
    with pytest.raises(HandoffError,match='DUPLICATE_BLOCK_BINDING'):build_lesson_handoff(r)


def test_bad_window_reference_rejected():
    r=options();r.target.bindings[0].candidate_start_ids=['window:unknown']
    with pytest.raises(HandoffError,match='INVALID_BLOCK_DOMAIN'):build_lesson_handoff(r)


def test_incompatible_block_patterns_fail_closed_instead_of_losing_synchronisation():
    r=options();r.target.templates[0].occurrences[0].key='occ:unmatched'
    with pytest.raises(HandoffError,match='UNSUPPORTED_BLOCK_PATTERN'):build_lesson_handoff(r)


def test_learners_cannot_be_resectioned_by_lesson_placement():
    r=lessons();w=lesson_witness();byid={x.id:x for x in r.problem.participation_requests}
    for en in w.enrollment_assignments:
        request=byid[en.request_id]
        alternatives=[o.id for o in r.problem.offerings if o.activity_id==request.activity_id and o.id not in en.offering_ids]
        if alternatives:
            en.offering_ids=[alternatives[0]];break
    assert 'INVALID_OFFERING_SELECTION' in codes(placement_witness_errors(r.problem,w))


def test_synchronisation_is_checked_even_when_each_moved_lesson_is_individually_valid():
    r=lessons();w=lesson_witness();a=w.event_assignments[0]
    event=next(e for e in r.problem.events if e.id==a.event_id)
    a.start_window_id=event.placement.start_window_ids[1]
    errors=codes(placement_witness_errors(r.problem,w))
    assert 'BLOCK_SYNCHRONISATION_BROKEN' in errors
    assert 'INVALID_PLACEMENT' not in errors


def test_dropped_sync_rule_cannot_be_hidden_by_rehashing_output():
    r=lessons();r.problem.constraints.pop();rebuilt_output_digest(r)
    assert 'BLOCK_RULE_LOST' in codes(lesson_handoff_errors(r))


def test_changed_choice_cannot_be_hidden_by_rehashing_output():
    r=lessons()
    for req in r.problem.participation_requests:
        alternate=[o.id for o in r.problem.offerings if o.activity_id==req.activity_id and o.id not in req.eligible_offering_ids]
        if alternate:
            req.eligible_offering_ids=[alternate[0]];break
    rebuilt_output_digest(r)
    assert 'ACCEPTED_CHOICE_CHANGED' in codes(lesson_handoff_errors(r))


def test_changed_section_capacity_caught_by_reverse_check():
    r=lessons();r.problem.offerings[0].capacity+=1;rebuilt_output_digest(r)
    assert 'SECTION_DEMAND_CHANGED' in codes(lesson_handoff_errors(r))


def test_missing_traceability_caught():
    r=lessons();r.receipt.mappings=[x for x in r.receipt.mappings if x.source_kind!='CHOICE']
    assert 'REQUEST_LINEAGE_LOST' in codes(lesson_handoff_errors(r))


def test_foreign_handoff_fields_rejected():
    raw=options().model_dump(mode='json');raw['silently_regenerate_everything']=True
    with pytest.raises(ValidationError):OptionsHandoff.model_validate(raw)


def test_handoff_numeric_fields_do_not_accept_boolean_as_int():
    raw=options().model_dump(mode='json');raw['target']['model_version']=True
    with pytest.raises(ValidationError):OptionsHandoff.model_validate(raw)


@pytest.mark.parametrize('origin',['GRID','MANUAL','NORMALISED_IMPORT'])
def test_fixed_exam_handoff_does_not_require_other_grid_timetables(origin):
    req=exams('GRID' if origin=='GRID' else 'MANUAL');req.source_ref.origin=origin
    out=build_exam_handoff(req)
    assert not exam_handoff_errors(out)
    assert len(out.problem.sessions)==2 and len(out.problem.demands)==3
    assert out.receipt.readiness=='INPUT_VALIDATED_NOT_SOLVED'


def test_exam_source_not_mutated_and_result_context_not_aliased():
    r=exams();before=r.model_dump_json();out=build_exam_handoff(r)
    assert r.model_dump_json()==before
    out.problem.sessions[0].venue_id='room:B'
    assert out.request.source.sessions[0].venue_id=='room:A'


def test_fixed_dates_and_extra_time_survive_handoff():
    req=exams();out=build_exam_handoff(req)
    session=next(x for x in out.problem.sessions if x.id==session_id(req,'exam:A'))
    assert session.interval.end.hour==12 and session.interval.end.minute==45
    assert max(d.interval.end for d in out.problem.demands if d.session_id==session.id)==session.interval.end


def test_only_selected_exams_become_staffing_tasks():
    r=exams();r.target.selected_session_ids=['exam:A'];r.target.policies=r.target.policies[:1]
    out=build_exam_handoff(r)
    assert len(out.problem.sessions)==1
    assert len(out.source_reservations)==2 # full source context is retained read-only


def test_missing_coverage_policy_not_filled_with_invented_ratio():
    r=exams();r.target.policies.pop()
    with pytest.raises(HandoffError,match='COVERAGE_POLICY_INCOMPLETE'):build_exam_handoff(r)


def test_policy_gap_is_not_the_same_as_no_staff_solution_yet():
    r=exams();r.target.policies[0].bands[1].start_offset_minutes=181
    with pytest.raises(HandoffError,match='DEMAND_COVERAGE_GAP'):build_exam_handoff(r)


def test_policy_beyond_exam_end_rejected():
    r=exams();r.target.policies[0].bands[-1].end_offset_minutes=226
    with pytest.raises(HandoffError,match='INVALID_DEMAND_INTERVAL'):build_exam_handoff(r)


def test_unresolved_staff_id_rejected():
    r=exams();r.target.policies[0].bands[0].eligible_staff_ids=['staff:unknown']
    with pytest.raises(HandoffError,match='UNRESOLVED_STAFF_IDENTITY'):build_exam_handoff(r)


def test_impossible_staff_quantity_is_not_mislabelled_as_solved():
    r=exams();r.target.policies[0].bands[0].minimum_staff=100
    out=build_exam_handoff(r)
    assert out.receipt.readiness=='INPUT_VALIDATED_NOT_SOLVED'
    w=CoverageWitness(problem_id=out.problem.problem_id,model_version=1,duties=[])
    assert 'COVERAGE_GAP' in codes(coverage_errors(out.problem,w))


def test_exam_seats_checked_against_venue_capacity():
    r=exams();r.source.sessions[0].candidate_count=101;repin(r)
    with pytest.raises(HandoffError,match='EXAM_OVER_VENUE_CAPACITY'):build_exam_handoff(r)


def test_shared_hall_is_reserved_by_exams_once_not_again_per_invigilator():
    r=exams();r.source.venues[0].sharing='CUMULATIVE'
    for e in r.source.sessions:e.venue_id='room:A'
    repin(r);out=build_exam_handoff(r)
    assert sum(c.units for c in out.source_reservations)==100
    assert all(c.schedule_id==r.source_ref.schedule_id for c in out.source_reservations)
    assert not exam_handoff_errors(out)


def test_overcommitted_shared_hall_rejected():
    r=exams();r.source.venues[0].sharing='CUMULATIVE'
    for e in r.source.sessions:e.venue_id='room:A'
    r.source.sessions[1].candidate_count=41;repin(r)
    with pytest.raises(HandoffError,match='CAPACITY_EXCEEDED'):build_exam_handoff(r)


def test_colliding_exclusive_exam_venues_rejected():
    r=exams();r.source.sessions[1].venue_id='room:A';repin(r)
    with pytest.raises(HandoffError,match='RESOURCE_OVERLAP'):build_exam_handoff(r)


def test_moved_exam_detected_even_with_fresh_target_checksum():
    r=exam_result();s=r.problem.sessions[0]
    s.interval=s.interval.model_copy(update={'end':s.interval.end+timedelta(minutes=1)})
    rebuilt_output_digest(r)
    assert 'FIXED_EXAM_FACT_CHANGED' in codes(exam_handoff_errors(r))


def test_changed_staffing_minimum_detected_even_with_fresh_target_checksum():
    r=exam_result();r.problem.demands[0].minimum_staff=1;rebuilt_output_digest(r)
    assert 'COVERAGE_POLICY_CHANGED' in codes(exam_handoff_errors(r))


def test_missing_source_reservation_detected():
    r=exam_result();r.source_reservations.pop()
    assert 'SOURCE_RESERVATIONS_CHANGED' in codes(exam_handoff_errors(r))


def test_source_reservation_cannot_be_reassigned_to_staffing_schedule():
    r=exam_result();r.source_reservations[0].schedule_id=r.problem.schedule_id
    assert 'SOURCE_RESERVATIONS_CHANGED' in codes(exam_handoff_errors(r))


def test_resource_only_change_approved_without_applying_it():
    r,cur=changes();before=r.baseline.model_dump_json();report=review_staffing_change(r,cur)
    assert report.status=='VALIDATED_PROPOSAL_NOT_APPLIED'
    assert not report.findings and len(report.actual_changes)==1
    assert r.baseline.model_dump_json()==before
    assert len(report.complete_target_claims)==4
    assert len(report.source_reservations)==2
    assert report.duty_minutes_by_person['staff:I5']==105
    assert all(c.resource_id.startswith('staff:') for c in report.complete_target_claims)


def test_undeclared_change_rejected():
    r,cur=changes();r.declared_changes=[]
    assert 'CHANGE_MANIFEST_MISMATCH' in codes(review_staffing_change(r,cur).findings)


def test_fake_before_value_rejected():
    r,cur=changes();r.declared_changes[0].before='staff:I4'
    assert 'CHANGE_MANIFEST_MISMATCH' in codes(review_staffing_change(r,cur).findings)


def test_hidden_change_to_unselected_duty_rejected_even_if_declared():
    r,cur=changes();r.candidate.duties[3].resource_id='staff:I3'
    r.declared_changes=derive_changes(r.baseline,r.candidate)
    assert 'OUT_OF_SCOPE_CHANGE' in codes(review_staffing_change(r,cur).findings)


def test_timing_change_rejected_in_staff_only_review():
    r,cur=changes();d=r.candidate.duties[2]
    d.interval=d.interval.model_copy(update={'start':d.interval.start+timedelta(minutes=1)})
    r.declared_changes=derive_changes(r.baseline,r.candidate)
    c=codes(review_staffing_change(r,cur).findings)
    assert 'OUT_OF_SCOPE_CHANGE' in c and 'COVERAGE_GAP' in c


def test_removing_a_duty_is_not_an_authorised_staff_replacement():
    r,cur=changes();r.candidate.duties.pop()
    assert 'UNAUTHORISED_DUTY_SET_CHANGE' in codes(review_staffing_change(r,cur).findings)


def test_wrong_candidate_model_version_rejected():
    r,cur=changes();r.candidate.model_version=2
    assert 'WRONG_TARGET_RESULT' in codes(review_staffing_change(r,cur).findings)


def test_unknown_mutable_duty_rejected():
    r,cur=changes();r.mutable_duty_ids=['duty:unknown']
    assert 'INVALID_MUTABLE_SLICE' in codes(review_staffing_change(r,cur).findings)


def test_actual_complete_claims_catch_conflict_with_untouched_duty():
    r,cur=changes();r.candidate.duties[2].resource_id='staff:I4'
    r.declared_changes=derive_changes(r.baseline,r.candidate)
    report=review_staffing_change(r,cur)
    assert 'RESOURCE_OVERLAP' in codes(report.findings)
    assert len(report.complete_target_claims)==4


def test_client_cannot_supply_a_truncated_claim_list():
    r,_=changes();raw=r.model_dump(mode='json');raw['claims']=[]
    with pytest.raises(ValidationError):StaffingReviewRequest.model_validate(raw)


def test_changed_baseline_without_matching_digest_rejected():
    r,cur=changes();r.baseline.duties[0].resource_id='staff:I5'
    assert 'BASELINE_CONTENT_MISMATCH' in codes(review_staffing_change(r,cur).findings)


@pytest.mark.parametrize('which,field',[(0,'revision'),(0,'content_sha256'),(1,'revision'),(1,'content_sha256')])
def test_source_and_target_staleness_both_block_review(which,field):
    r,cur=changes()
    if field=='revision':cur[which].revision+=1
    else:cur[which].content_sha256='a'*64
    report=review_staffing_change(r,cur)
    assert report.status=='BLOCKED' and 'STALE_SNAPSHOT' in codes(report.findings)


def test_missing_authoritative_source_is_not_assumed_fresh():
    r,cur=changes()
    assert 'SOURCE_NOT_AVAILABLE' in codes(review_staffing_change(r,cur[1:]).findings)


def test_rejected_review_never_mutates_an_upstream_exam():
    r,cur=changes();original=r.handoff.request.source.model_dump_json()
    cur[0].revision+=1;review_staffing_change(r,cur)
    assert r.handoff.request.source.model_dump_json()==original


def test_duplicate_authoritative_snapshot_rejected():
    r,cur=changes();cur.append(copy.deepcopy(cur[0]))
    assert 'DUPLICATE_SNAPSHOT' in codes(review_staffing_change(r,cur).findings)


def test_resource_claims_not_invented_for_abstract_cycle_days():
    r=lessons()
    with pytest.raises(HandoffError,match='UNRESOLVED_CALENDAR'):
        derive_dated_placement_claims(r.problem,lesson_witness())


def test_dated_placement_claims_include_every_student_teacher_and_room():
    r=options()
    for i,d in enumerate(r.target.days): d.date=date(2027,1,11)+timedelta(days=i)
    out=build_lesson_handoff(r);w=lesson_witness()
    claims=derive_dated_placement_claims(out.problem,w)
    # Four sections with 4,2,4,2 learners; two events each = 24 pupil claims;
    # eight teacher claims and eight room claims = 40 total.
    assert len(claims)==40
    assert sum(c.resource_id.startswith('learner:') for c in claims)==24
    assert sum(c.resource_id.startswith('teacher:') for c in claims)==8
    assert sum(c.resource_id.startswith('room:') for c in claims)==8
    assert len({c.id for c in claims})==40


def test_hash_mapping_key_order_does_not_matter_but_list_order_does():
    assert fingerprint({'b':2,'a':1})==fingerprint({'a':1,'b':2})
    assert fingerprint([1,2])!=fingerprint([2,1])


def test_equal_instants_with_different_offsets_have_equal_typed_fingerprints():
    r=exams();x=r.source.model_copy(deep=True)
    for s in x.sessions:
        s.supervision_interval=s.supervision_interval.model_copy(update={
            'start':s.supervision_interval.start.astimezone(timezone.utc),
            'end':s.supervision_interval.end.astimezone(timezone.utc)})
    assert fingerprint(x)==fingerprint(r.source)


def test_delimiter_in_source_id_cannot_collide_with_multiple_id_parts():
    assert stable_id('event','a:b','c')!=stable_id('event','a','b:c')


@pytest.mark.parametrize('schema,folder,name',[
    ('options-handoff','H1_options_to_lessons','request.json'),
    ('lesson-handoff-result','H1_options_to_lessons','handoff.json'),
    ('placement-witness-v04','H1_options_to_lessons','placement-witness.json'),
    ('exam-handoff','H2_grid_exams_to_coverage','request.json'),
    ('exam-handoff-result','H2_grid_exams_to_coverage','handoff.json'),
    ('exam-handoff','H3_manual_exams_to_coverage','request.json'),
    ('staffing-review-request','H4_staffing_only_change','review-request.json'),
    ('staffing-review-result','H4_staffing_only_change','review-result.json'),
])
def test_new_fixtures_validate_against_generated_json_schemas(schema,folder,name):
    spec=json.loads((ROOT/'schemas'/f'{schema}.schema.json').read_text())
    Draft202012Validator.check_schema(spec)
    assert not list(Draft202012Validator(spec,format_checker=FormatChecker()).iter_errors(load(folder,name)))

@pytest.mark.parametrize('kind',['lessons','exams'])
def test_wrong_adapter_identity_in_receipt_is_rejected(kind):
    r=lessons() if kind=='lessons' else exam_result()
    r.receipt.adapter_id='EXAMS_TO_COVERAGE' if kind=='lessons' else 'OPTIONS_TO_LESSONS'
    checker=lesson_handoff_errors if kind=='lessons' else exam_handoff_errors
    assert 'HANDOFF_IDENTITY_MISMATCH' in codes(checker(r))

@pytest.mark.parametrize('kind',['lessons','exams'])
def test_wrong_target_schema_in_receipt_is_rejected(kind):
    r=lessons() if kind=='lessons' else exam_result()
    r.receipt.target_schema_version='9.9-unknown'
    checker=lesson_handoff_errors if kind=='lessons' else exam_handoff_errors
    assert 'RECEIPT_TARGET_MISMATCH' in codes(checker(r))

@pytest.mark.parametrize('kind',['lessons','exams'])
def test_mapping_components_are_explicit_and_cannot_be_silently_changed(kind):
    r=lessons() if kind=='lessons' else exam_result()
    mapping=next(m for m in r.receipt.mappings if m.source_component is not None)
    mapping.source_component='component:wrong'
    checker=lesson_handoff_errors if kind=='lessons' else exam_handoff_errors
    assert 'LINEAGE_MANIFEST_MISMATCH' in codes(checker(r))

@pytest.mark.parametrize('kind',['lessons','exams'])
def test_extra_lineage_mapping_rejected(kind):
    r=lessons() if kind=='lessons' else exam_result()
    r.receipt.mappings.append(copy.deepcopy(r.receipt.mappings[0]))
    checker=lesson_handoff_errors if kind=='lessons' else exam_handoff_errors
    assert 'LINEAGE_MANIFEST_MISMATCH' in codes(checker(r))
