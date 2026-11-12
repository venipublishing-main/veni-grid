from __future__ import annotations
import copy,json
from pathlib import Path
from datetime import date
import pytest
from pydantic import ValidationError
from jsonschema import Draft202012Validator
from veni_grid_contract.models import SchedulingProblem,SchedulingSolution
from veni_grid_contract.validation import witness_issues
from veni_grid_contract.primitives import CapacityResource,Interval,ResourceClaim,usage_errors
from veni_grid_contract.jobs import SchedulingJob,JobProposal,ScheduleVersion,proposal_errors
from veni_grid_contract.option_design import OptionDesignProblem,OptionDesignWitness,option_errors
from veni_grid_contract.coverage import CoverageProblem,CoverageWitness,coverage_errors,duty_minutes
from veni_grid_contract.calendar_projection import CalendarProjection,project_calendar,resolve_local

ROOT=Path(__file__).resolve().parents[1]
def read(case,filename='problem'):
    return json.loads((ROOT/'fixtures_v03'/case/f'{filename}.json').read_text())
def pair(case):return read(case),read(case,'witness')
def codes(issues):return {i.code for i in issues}
def share(p,w):return witness_issues(SchedulingProblem.model_validate(p),SchedulingSolution.model_validate(w))
def option(p,w):return option_errors(OptionDesignProblem.model_validate(p),OptionDesignWitness.model_validate(w))
def coverage(p,w):return coverage_errors(CoverageProblem.model_validate(p),CoverageWitness.model_validate(w))
def jobcheck(p,w,current=None):
    current=read('J1_linked_scoped_job','current_versions') if current is None else current
    return proposal_errors(SchedulingJob.model_validate(p),JobProposal.model_validate(w),[ScheduleVersion.model_validate(x) for x in current])

SCHEMAS=[('F1_shared_capacity','problem','scheduling-problem'),('F1_shared_capacity','witness','scheduling-solution'),
('F2_option_design','problem','option-design-problem'),('F2_option_design','witness','option-design-witness'),
('F2b_1500_choice_representation','problem','option-design-problem'),('F2b_1500_choice_representation','witness','option-design-witness'),
('F3_segmented_invigilation','problem','coverage-problem'),('F3_segmented_invigilation','witness','coverage-witness'),
('F4_cycle_calendar','problem','calendar-projection'),('J1_linked_scoped_job','problem','scheduling-job'),('J1_linked_scoped_job','witness','job-proposal')]
@pytest.mark.parametrize('case,filename,schema_name',SCHEMAS)
def test_extension_schema_and_roundtrip(case,filename,schema_name):
    schema=json.loads((ROOT/'schemas'/f'{schema_name}.schema.json').read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(read(case,filename))

# F1: shared capacity is not permission to double-book staff.
def test_shared_hall_exactly_full_is_valid():
    assert share(*pair('F1_shared_capacity'))==[]
def test_cumulative_hall_one_seat_over_is_rejected():
    p,w=pair('F1_shared_capacity');p['events'][1]['requirements'][0]['usage_units']=41
    assert 'CAPACITY_EXCEEDED' in codes(share(p,w))
def test_exclusive_hall_still_forbids_overlap():
    p,w=pair('F1_shared_capacity');p['resources'][0]['sharing_mode']='EXCLUSIVE'
    assert 'RESOURCE_OVERLAP' in codes(share(p,w))
def test_shared_hall_does_not_allow_shared_teacher():
    p,w=pair('F1_shared_capacity');w['event_assignments'][1]['resource_allocations'][1]['resource_ids']=['staff:A']
    assert 'RESOURCE_OVERLAP' in codes(share(p,w))
def test_missing_cumulative_consumption_not_guessed():
    p,w=pair('F1_shared_capacity');p['events'][0]['requirements'][0].pop('usage_units')
    assert 'MISSING_USAGE_UNITS' in codes(share(p,w))
def test_cumulative_sharing_cannot_be_enabled_for_people():
    p,w=pair('F1_shared_capacity');p['resources'][3].update(sharing_mode='CUMULATIVE',capacity=2)
    with pytest.raises(ValidationError):SchedulingProblem.model_validate(p)
def test_adjacent_hall_uses_release_before_next_use():
    p,w=pair('F1_shared_capacity');p['windows'][1]['start_minute']=660
    p['events'][1]['requirements'][0]['usage_units']=100
    assert share(p,w)==[]
def test_one_event_exceeds_shared_hall_capacity_even_without_competitor():
    p,w=pair('F1_shared_capacity');p['windows'][1]['start_minute']=660;p['events'][1]['requirements'][0]['usage_units']=101
    assert 'CAPACITY_EXCEEDED' in codes(share(p,w))

# F2: independently validate designed sections, not a scheduler.
@pytest.mark.parametrize('case',['F2_option_design','F2b_1500_choice_representation'])
def test_option_input_has_no_preassigned_sections_or_blocks(case):
    p,w=pair(case)
    assert 'offerings' not in p and 'block_ids' not in p
    assert option(p,w)==[]
def test_1500_learner_shape_has_3000_requests_120_created_sections():
    p,w=pair('F2b_1500_choice_representation')
    assert (len(p['participant_ids']),len(p['requests']),len(w['offerings']))==(1500,3000,120)
def test_learner_block_clash_in_designed_sections():
    p,w=pair('F2_option_design');w['offerings'][1]['block_id']=w['offerings'][0]['block_id']
    assert 'LEARNER_BLOCK_CLASH' in codes(option(p,w))
def test_section_demand_cannot_be_silently_dropped():
    p,w=pair('F2_option_design');w['allocations'].pop()
    assert 'UNFULFILLED_REQUESTS' in codes(option(p,w))
def test_designed_section_capacity():
    p,w=pair('F2_option_design');p['families'][0]['max_members']=1
    assert 'SECTION_CAPACITY' in codes(option(p,w))
def test_designed_section_count_limit():
    p,w=pair('F2_option_design');p['families'][1]['max_sections']=1
    assert 'SECTION_LIMIT' in codes(option(p,w))
def test_option_wrong_subject_allocation_rejected():
    p,w=pair('F2_option_design');w['allocations'][0]['offering_id']=w['offerings'][1]['id']
    assert 'WRONG_SUBJECT' in codes(option(p,w))
def test_option_duplicate_choice_rejected():
    p,w=pair('F2_option_design');w['allocations'].append(copy.deepcopy(w['allocations'][0]))
    assert 'DUPLICATE_CHOICE_ALLOCATION' in codes(option(p,w))
def test_option_unknown_participant_rejected():
    p,w=pair('F2_option_design');p['requests'][0]['participant_id']='learner:unknown'
    assert 'BROKEN_CHOICE_REQUEST' in codes(option(p,w))
def test_options_too_many_blocks_rejected():
    p,w=pair('F2_option_design');w['block_ids'].append('block:third')
    assert 'INVALID_BLOCKS' in codes(option(p,w))
def test_empty_designed_section_rejected():
    p,w=pair('F2_option_design');w['offerings'].append({'id':'section:empty','family_id':'family:Physics','block_id':'block:one'})
    assert 'SECTION_CAPACITY' in codes(option(p,w))

# F3: continuous headcount, not total duty minutes.
def test_relief_and_extra_time_witness_valid():
    assert coverage(*pair('F3_segmented_invigilation'))==[]
def test_segmented_duty_hours_are_actual_minutes():
    p,w=pair('F3_segmented_invigilation')
    assert duty_minutes(CoverageWitness.model_validate(w))=={'staff:I1':75,'staff:I2':225,'staff:I3':105,'staff:I4':180}
def test_one_minute_relief_gap_rejected():
    p,w=pair('F3_segmented_invigilation');w['duties'][2]['interval']['start']='2027-01-11T10:16:00+02:00'
    assert 'COVERAGE_GAP' in codes(coverage(p,w))
def test_extra_time_uncovered_rejected():
    p,w=pair('F3_segmented_invigilation');w['duties'][1]['interval']['end']='2027-01-11T12:00:00+02:00'
    assert 'COVERAGE_GAP' in codes(coverage(p,w))
def test_staff_cannot_supervise_two_venues_at_once():
    p,w=pair('F3_segmented_invigilation');w['duties'][3]['resource_id']='staff:I2'
    assert 'RESOURCE_OVERLAP' in codes(coverage(p,w))
def test_duplicate_same_person_not_two_people():
    p,w=pair('F3_segmented_invigilation');w['duties'][2]['resource_id']='staff:I2'
    assert {'RESOURCE_OVERLAP','COVERAGE_GAP'}<=codes(coverage(p,w))
def test_staff_partial_availability_applies():
    p,w=pair('F3_segmented_invigilation');w['duties'][0]['interval']['end']='2027-01-11T10:16:00+02:00'
    assert 'RESOURCE_UNAVAILABLE' in codes(coverage(p,w))
def test_staff_eligibility_per_coverage_interval():
    p,w=pair('F3_segmented_invigilation');w['duties'][2]['resource_id']='staff:I4'
    assert 'STAFF_INELIGIBLE' in codes(coverage(p,w))
def test_staffing_output_cannot_retime_source_exam():
    p,w=pair('F3_segmented_invigilation');w['exam_time_changes']=[]
    with pytest.raises(ValidationError):CoverageWitness.model_validate(w)
def test_coverage_unknown_role_not_counted():
    p,w=pair('F3_segmented_invigilation');w['duties'][2]['role']='UNKNOWN'
    assert {'DUTY_WITHOUT_DEMAND','COVERAGE_GAP'}<=codes(coverage(p,w))
def test_coverage_demand_must_be_inside_session():
    p,w=pair('F3_segmented_invigilation');p['demands'][0]['interval']['end']='2027-01-11T13:00:00+02:00'
    assert 'INVALID_DEMAND_INTERVAL' in codes(coverage(p,w))

# F4: independently check a few known calendar dates against the projection.
def test_10_day_projection_matches_frozen_witness():
    p=CalendarProjection.model_validate(read('F4_cycle_calendar'))
    out=[x.model_dump(mode='json') for x in project_calendar(p)]
    assert out==read('F4_cycle_calendar','witness')['occurrences'];assert len(out)==23
def test_closure_pauses_cycle_and_has_no_lessons():
    out=project_calendar(CalendarProjection.model_validate(read('F4_cycle_calendar')))
    assert all(o.date!=date(2027,1,13) for o in out)
    assert {o.cycle_day for o in out if o.date==date(2027,1,14)}=={3}
def test_cycle_wraps_after_day_ten():
    out=project_calendar(CalendarProjection.model_validate(read('F4_cycle_calendar')))
    assert {o.cycle_day for o in out if o.date==date(2027,1,26)}=={1}
def test_changed_bells_apply_to_just_one_date():
    out=project_calendar(CalendarProjection.model_validate(read('F4_cycle_calendar')))
    assert {o.interval.start.minute for o in out if o.date==date(2027,1,14)}=={30}
    assert {o.interval.start.minute for o in out if o.date==date(2027,1,15)}=={0}
def test_exam_cancellation_preserves_unrelated_group_and_base_pattern():
    raw=read('F4_cycle_calendar');before=copy.deepcopy(raw)
    out=project_calendar(CalendarProjection.model_validate(raw))
    assert [o.event_id for o in out if o.date==date(2027,1,19)]==['lesson:B:6']
    assert raw==before and len(raw['patterns'])==20
def test_no_exam_override_means_no_implicit_cancellation():
    raw=read('F4_cycle_calendar');raw['cancellations']=[]
    out=project_calendar(CalendarProjection.model_validate(raw))
    assert {o.event_id for o in out if o.date==date(2027,1,19)}=={'lesson:A:6','lesson:B:6'}
def test_closed_day_can_explicitly_advance_cycle():
    raw=read('F4_cycle_calendar');raw['exceptions'][0]['advance_cycle']=True;raw['cancellations']=[]
    out=project_calendar(CalendarProjection.model_validate(raw))
    assert {o.cycle_day for o in out if o.date==date(2027,1,14)}=={4}
def test_wrong_cancellation_target_is_not_silently_ignored():
    raw=read('F4_cycle_calendar');raw['cancellations'][0]['pattern_id']='pattern:A:5'
    with pytest.raises(ValueError,match='actual occurrence'):project_calendar(CalendarProjection.model_validate(raw))
@pytest.mark.parametrize('day,minute',[(date(2026,3,8),150),(date(2026,11,1),90)])
def test_dst_gap_and_fold_fail_closed(day,minute):
    with pytest.raises(ValueError,match='Ambiguous or nonexistent'):resolve_local(day,minute,'America/New_York')
def test_offset_equivalent_times_compare_on_utc():
    a=Interval(start='2027-01-11T09:00:00+02:00',end='2027-01-11T10:00:00+02:00')
    b=Interval(start='2027-01-11T07:30:00Z',end='2027-01-11T08:30:00Z')
    assert a.overlaps(b)

# Scope guards: same foundation, never compulsory all-in-one processing.
def test_linked_job_valid_and_no_inputs_mutated():
    p,w=pair('J1_linked_scoped_job');original=copy.deepcopy(p)
    assert jobcheck(p,w)==[];assert p==original

def test_standalone_job_needs_no_other_timetable():
    p,w=pair('J1_linked_scoped_job');p['mode']='STANDALONE';p['dependencies']=[];w['dependency_versions']=[]
    assert jobcheck(p,w,current=p['targets'])==[]

def test_respect_existing_does_not_grant_write_permission_to_exams():
    p,w=pair('J1_linked_scoped_job');w['changes'].append({'schedule_id':'schedule:exams','entity_id':'exam:one','field':'TIME','before':'09:00','after':'10:00'})
    assert 'OUT_OF_SCOPE_CHANGE' in codes(jobcheck(p,w))

def test_repair_does_not_modify_unselected_duty():
    p,w=pair('J1_linked_scoped_job');w['changes'][0]['entity_id']='duty:two'
    assert 'OUT_OF_SCOPE_CHANGE' in codes(jobcheck(p,w))

def test_staff_only_repair_cannot_move_time():
    p,w=pair('J1_linked_scoped_job');w['changes'][0]['field']='TIME'
    assert 'OUT_OF_SCOPE_CHANGE' in codes(jobcheck(p,w))

def test_repair_respects_busy_teacher_from_other_schedule():
    p,w=pair('J1_linked_scoped_job');w['claims'][0]['resource_id']='staff:busy'
    assert 'RESOURCE_OVERLAP' in codes(jobcheck(p,w))

def test_latest_dependency_changed_requires_revalidation():
    p,w=pair('J1_linked_scoped_job');current=read('J1_linked_scoped_job','current_versions');current[1]['revision']=8
    assert 'STALE_SNAPSHOT' in codes(jobcheck(p,w,current))

def test_content_fingerprint_change_also_invalidates():
    p,w=pair('J1_linked_scoped_job');current=read('J1_linked_scoped_job','current_versions');current[1]['content_sha256']='f'*64
    assert 'STALE_SNAPSHOT' in codes(jobcheck(p,w,current))

def test_wrong_target_baseline_rejected():
    p,w=pair('J1_linked_scoped_job');w['target_versions'][0]['revision']=2
    assert 'TARGET_VERSION_MISMATCH' in codes(jobcheck(p,w))

def test_joint_not_implicitly_enabled_by_multiple_targets():
    p,w=pair('J1_linked_scoped_job');p['targets'].append(p['dependencies'][0]['source'])
    with pytest.raises(ValidationError):SchedulingJob.model_validate(p)

def test_joint_explicit_opt_in_required():
    p,w=pair('J1_linked_scoped_job');p['mode']='JOINT';p['targets'].append(p['dependencies'].pop(0)['source'])
    p['mutable'].append({'schedule_id':'schedule:exams','entity_ids':['exam:one'],'fields':['TIME']})
    with pytest.raises(ValidationError):SchedulingJob.model_validate(p)
    p['joint_authorised']=True
    assert SchedulingJob.model_validate(p).mode=='JOINT'

def test_foreign_job_result_rejected():
    p,w=pair('J1_linked_scoped_job');w['job_id']='job:other'
    assert 'WRONG_JOB' in codes(jobcheck(p,w))

def test_outside_horizon_claim_rejected():
    p,w=pair('J1_linked_scoped_job');w['claims'][0]['interval']['end']='2027-01-11T14:00:00+02:00'
    assert 'OUTSIDE_JOB_HORIZON' in codes(jobcheck(p,w))

def test_standalone_cannot_hide_supplied_dependencies():
    p,w=pair('J1_linked_scoped_job');p['mode']='STANDALONE'
    with pytest.raises(ValidationError):SchedulingJob.model_validate(p)

def test_partial_commitment_source_identity_mismatch_rejected():
    p,w=pair('J1_linked_scoped_job');p['dependencies'][0]['claims'][0]['schedule_id']='schedule:other'
    with pytest.raises(ValidationError):SchedulingJob.model_validate(p)


def test_coverage_input_cannot_omit_extra_time_demand():
    p,w=pair('F3_segmented_invigilation');p['demands'].pop(1)
    assert 'DEMAND_COVERAGE_GAP' in codes(coverage(p,w))

def test_scope_protects_other_duty_on_same_schedule():
    p,w=pair('J1_linked_scoped_job')
    p['preserved_claims']=[{'id':'claim:untouched:duty','schedule_id':'schedule:invigilation','entity_id':'duty:two',
        'resource_id':'staff:free','interval':{'start':'2027-01-11T10:00:00+02:00','end':'2027-01-11T11:00:00+02:00'}}]
    assert 'RESOURCE_OVERLAP' in codes(jobcheck(p,w))

def test_resource_claim_from_another_schedule_not_invented_in_output():
    p,w=pair('J1_linked_scoped_job');w['claims'][0]['schedule_id']='schedule:exams'
    assert 'OUT_OF_SCOPE_CLAIM' in codes(jobcheck(p,w))

def test_cross_calendar_exam_clash_remains_until_explicit_override():
    p=read('F4_cycle_calendar');p['cancellations']=[]
    occurrence=next(o for o in project_calendar(CalendarProjection.model_validate(p))
                    if o.date==date(2027,1,19) and o.event_id=='lesson:A:6')
    exam=ResourceClaim(id='claim:exam',schedule_id='schedule:exams',entity_id='exam:one',resource_id='room:one',
        interval=Interval(start='2027-01-19T08:00:00+02:00',end='2027-01-19T11:00:00+02:00'))
    lesson=ResourceClaim(id='claim:lesson',schedule_id='schedule:academic',entity_id=occurrence.event_id,resource_id='room:one',interval=occurrence.interval)
    assert 'RESOURCE_OVERLAP' in codes(usage_errors([CapacityResource(id='room:one',kind='SPACE')],[exam,lesson]))
