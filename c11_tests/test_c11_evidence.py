"""C11 local proof of exact canonical bytes, versioned scope and hard rejection."""
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

import pytest

from veni_grid_authority.c11_evidence import (
    C11EvidenceRejected, CONTRACT_VERSION, SERIALIZER, SourceBinding,
    create_evidence, grid_json_1, verify_evidence,
)
from veni_grid_contract.handoff_common import fingerprint


def denies(code, call):
    with pytest.raises(C11EvidenceRejected) as e:
        call()
    assert e.value.code == code


def repack(ev, document):
    raw = grid_json_1(document)
    data = raw.encode('utf-8')
    return replace(ev, canonical_json=raw, canonical_utf8_length=len(data),
                   sha256=sha256(data).hexdigest())


def document(ev):
    return json.loads(ev.canonical_json)


def test_full_invented_accepted_options_roundtrip_and_legacy_fingerprint_parity(example):
    candidate, binding, evidence = example
    assert len(candidate.demand.requests) == 48
    assert verify_evidence(evidence, binding=binding) == candidate
    assert evidence.contract_version == CONTRACT_VERSION and evidence.serializer == SERIALIZER
    assert sha256(evidence.canonical_json.encode('utf-8')).hexdigest() == evidence.sha256
    assert grid_json_1(candidate).encode('utf-8') == (
        grid_json_1(candidate.model_dump(mode='python')).encode('utf-8'))
    assert sha256(grid_json_1(candidate).encode('utf-8')).hexdigest() == fingerprint(candidate)
    assert document(evidence)['accepted_options_grid_json_1_sha256'] == fingerprint(candidate)


def test_json_key_order_independent_but_array_order_remains_significant():
    one = {'z': [{'β': 2, 'a': 1}], 'a': 'München 😀'}
    other = {'a': 'München 😀', 'z': [{'a': 1, 'β': 2}]}
    assert grid_json_1(one) == grid_json_1(other)
    assert grid_json_1({'arr': ['x', 'y']}) != grid_json_1({'arr': ['y', 'x']})
    assert 'München 😀' in grid_json_1(one)
    assert ' ' not in grid_json_1({'x': 1, 'y': 2})


def test_datetime_conforms_to_existing_grid_json_1_utc_normalisation():
    local = datetime(2026, 11, 17, 12, tzinfo=timezone(timedelta(hours=2)))
    utc = local.astimezone(timezone.utc)
    assert grid_json_1({'when': local}) == grid_json_1({'when': utc})
    assert sha256(grid_json_1({'when': local}).encode('utf-8')).hexdigest() == fingerprint({'when': local})


def test_naive_and_nonfinite_values_rejected():
    denies('GRID_JSON_1_UNSUPPORTED_VALUE', lambda: grid_json_1({'v': float('nan')}))
    # The C11 wrapper preserves the inherited refusal but uses a new code.
    denies('GRID_JSON_1_UNSUPPORTED_VALUE', lambda: grid_json_1({'when': datetime(2026, 11, 17)}))
    denies('GRID_JSON_1_UNSUPPORTED_VALUE', lambda: grid_json_1({'wrong': object()}))
    denies('GRID_JSON_1_UNSUPPORTED_VALUE', lambda: grid_json_1({'unusable': 'bad\x00label'}))


@pytest.mark.parametrize('field', ['organisation_uuid', 'schedule_uuid'])
def test_invalid_server_scope_uuid_is_refused(example, field):
    _, binding, _ = example
    denies('SERVER_SCOPE_UUID_REQUIRED', lambda: replace(binding, **{field: 'not-a-uuid'}))


@pytest.mark.parametrize('revision', [0, -1, True, '1'])
def test_source_revision_is_a_strict_positive_integer(example, revision):
    _, binding, _ = example
    denies('POSITIVE_SOURCE_REVISION_REQUIRED', lambda: replace(binding, source_revision=revision))


@pytest.mark.parametrize('field', ['source_grid_json_1_sha256', 'c4_validated_teaching_sha256'])
def test_source_review_hash_format_is_pinned(example, field):
    _, binding, _ = example
    denies('SHA256_FORMAT_REQUIRED', lambda: replace(binding, **{field: 'AB'*32}))


def test_changed_byte_count_and_checksum_rejected(example):
    _, binding, ev = example
    denies('CANONICAL_BYTE_LENGTH_MISMATCH', lambda: verify_evidence(
        replace(ev, canonical_utf8_length=ev.canonical_utf8_length + 1), binding=binding))
    denies('CANONICAL_BYTES_SHA256_MISMATCH', lambda: verify_evidence(
        replace(ev, sha256='f'*64), binding=binding))


def test_noncanonical_whitespace_rejected_even_after_attacker_recomputes_sha256(example):
    _, binding, ev = example
    raw = ev.canonical_json + '\n'
    changed = replace(ev, canonical_json=raw, canonical_utf8_length=len(raw.encode('utf-8')),
                      sha256=sha256(raw.encode('utf-8')).hexdigest())
    denies('NONCANONICAL_GRID_JSON_1', lambda: verify_evidence(changed, binding=binding))


def test_duplicate_keys_rejected_even_with_matching_new_digest(example):
    _, binding, ev = example
    raw = '{"serializer":"GRID-JSON-1",' + ev.canonical_json[1:]
    changed = replace(ev, canonical_json=raw, canonical_utf8_length=len(raw.encode('utf-8')),
                      sha256=sha256(raw.encode('utf-8')).hexdigest())
    denies('DUPLICATE_JSON_KEY', lambda: verify_evidence(changed, binding=binding))


@pytest.mark.parametrize('field', ['organisation_uuid','schedule_uuid','source_revision',
                                   'source_grid_json_1_sha256','c4_validated_teaching_sha256'])
def test_replay_across_school_schedule_revision_or_review_is_refused(example, field):
    _, binding, ev = example
    changed = (2 if field == 'source_revision' else str(uuid4()) if field.endswith('uuid') else 'b'*64)
    other = replace(binding, **{field: changed})
    denies('SERVER_SOURCE_SCOPE_MISMATCH', lambda: verify_evidence(ev, binding=other))


@pytest.mark.parametrize('field,value,code', [
    ('contract_version', 'legacy-version', 'ENVELOPE_KIND_OR_PROFILE_MISMATCH'),
    ('serializer', 'postgres-jsonb-text', 'ENVELOPE_KIND_OR_PROFILE_MISMATCH'),
    ('schedule_kind', 'EXAMINATIONS', 'ENVELOPE_KIND_OR_PROFILE_MISMATCH'),
])
def test_rehashed_envelope_cannot_change_protocol_or_timetable_kind(example, field, value, code):
    _, binding, ev = example
    payload = document(ev);payload[field] = value
    denies(code, lambda: verify_evidence(repack(ev,payload), binding=binding))


def test_rehashed_extra_envelope_field_refused(example):
    _, binding, ev = example
    payload = document(ev);payload['client_claimed_role']='OWNER'
    denies('INVALID_ENVELOPE_SHAPE', lambda: verify_evidence(repack(ev,payload), binding=binding))


def test_rehashed_but_missing_learner_allocation_rejected_by_independent_options_checker(example):
    _, binding, ev = example
    payload = document(ev);payload['accepted_options']['plan']['allocations'].pop()
    denies('INVALID_OPTIONS_WITNESS', lambda: verify_evidence(repack(ev,payload), binding=binding))


def test_rehashed_wrong_embedded_candidate_fingerprint_refused(example):
    _, binding, ev = example
    payload = document(ev);payload['accepted_options_grid_json_1_sha256'] = 'f'*64
    denies('ACCEPTED_OPTIONS_FINGERPRINT_MISMATCH', lambda: verify_evidence(
        repack(ev,payload), binding=binding))


def test_versioned_top_level_evidence_metadata_cannot_be_changed(example):
    _, binding, ev = example
    denies('UNSUPPORTED_EVIDENCE_PROFILE', lambda: verify_evidence(
        replace(ev,serializer='JSONB_TEXT'), binding=binding))


def test_new_evidence_requires_independently_validated_option_witness(example):
    candidate, binding, _ = example
    bad = candidate.model_copy(deep=True);bad.plan.allocations.pop()
    denies('INVALID_OPTIONS_WITNESS', lambda: create_evidence(bad, binding=binding))
    denies('TYPED_OPTIONS_REQUIRED', lambda: create_evidence({'demand':'forged'}, binding=binding))


def test_c11_does_not_modify_earlier_contracts_c9_or_supabase_migrations():
    root = Path(__file__).resolve().parents[1]
    code = (root / 'veni_grid_authority/c11_evidence.py').read_text()
    sql = (root / 'db/c11/c11_isolated_hash_gate.sql').read_text()
    assert 'class EvidenceV1' in code and 'class SourceBinding' in code
    assert 'C11_DISPOSABLE_PG17_ONLY' in sql and 'SECURITY INVOKER' in sql
    assert 'SECURITY DEFINER' not in sql
    assert not (root / 'supabase/migrations').exists()
