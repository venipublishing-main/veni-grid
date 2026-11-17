"""True PostgreSQL 17 byte-parity tests, disposable local CI service ONLY.

Never point GRID_C11_PG_DSN at Supabase or any production/staging project.
The name, local network and superuser/major version are verified before DDL.
"""
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from veni_grid_authority.c11_evidence import SourceBinding, create_evidence
from veni_grid_contract.handoff_common import fingerprint
from veni_grid_contract.options_handoff import AcceptedOptions

ROOT = Path(__file__).resolve().parents[1]
CHECK_SQL = """SELECT grid_c11.verify_options_evidence_v1(
   %s::text, %s::jsonb, %s::text, %s::integer, %s::uuid, %s::uuid,
   %s::integer, %s::text, %s::text)"""


@pytest.fixture(scope="session")
def pg11_setup():
    import psycopg
    from psycopg.conninfo import conninfo_to_dict

    dsn = os.environ.get("GRID_C11_PG_DSN", "")
    if os.environ.get("GRID_C11_DISPOSABLE_ONLY") != "YES" or not dsn:
        raise RuntimeError("C11 refuses PG without explicit disposable test gate")
    parsed = conninfo_to_dict(dsn)
    if (parsed.get("dbname") != "grid_c11_isolated"
            or parsed.get("host") not in ("localhost", "127.0.0.1")
            or parsed.get("hostaddr") not in (None, "127.0.0.1")
            or parsed.get("user") != "postgres"):
        raise RuntimeError("C11 refuses a nonlocal or incorrectly named PostgreSQL target")

    with psycopg.connect(dsn, autocommit=True, connect_timeout=8) as db:
        name, role, version = db.execute(
            "SELECT current_database(),current_user,current_setting('server_version_num')::int"
        ).fetchone()
        if name != "grid_c11_isolated" or role != "postgres" or not 170000 <= version < 180000:
            raise RuntimeError("C11 refuses non-disposable PostgreSQL context")
        db.execute("SET grid.c11_disposable_only = 'YES'")
        db.execute((ROOT / 'db/c11/c11_isolated_hash_gate.sql').read_text(), prepare=False)
        db.execute("CREATE ROLE grid_c11_guest NOLOGIN NOSUPERUSER NOBYPASSRLS")
    return {"dsn": dsn, "version": version, "database": name}


def arguments(ev, binding, raw_jsonb=None):
    return (ev.canonical_json, raw_jsonb if raw_jsonb is not None else ev.canonical_json,
            ev.sha256, ev.canonical_utf8_length, binding.organisation_uuid,
            binding.schedule_uuid, binding.source_revision,
            binding.source_grid_json_1_sha256, binding.c4_validated_teaching_sha256)


def verified(pg11_setup, ev, binding, raw_jsonb=None):
    import psycopg
    with psycopg.connect(pg11_setup['dsn'], connect_timeout=8) as db:
        return db.execute(CHECK_SQL, arguments(ev, binding, raw_jsonb)).fetchone()[0]


def refused(pg11_setup, ev, binding, message, raw_jsonb=None):
    import psycopg
    with psycopg.connect(pg11_setup['dsn'], connect_timeout=8) as db:
        with pytest.raises(psycopg.Error, match=message):
            db.execute(CHECK_SQL, arguments(ev, binding, raw_jsonb))


def test_real_postgresql_hashes_exact_original_python_utf8_bytes(example, pg11_setup):
    _, binding, ev = example
    assert verified(pg11_setup, ev, binding) is True


def test_jsonb_text_hash_is_demonstrably_different_and_not_silently_accepted(example, pg11_setup):
    import psycopg
    _, binding, ev = example
    with psycopg.connect(pg11_setup['dsn']) as db:
        db_text, db_hash = db.execute(
            "SELECT (%s::jsonb)::text,encode(public.digest(convert_to((%s::jsonb)::text,'UTF8'),'sha256'),'hex')",
            (ev.canonical_json, ev.canonical_json)).fetchone()
    assert db_text != ev.canonical_json
    assert db_hash != ev.sha256
    # Yet the SQL verifier hashes the original canonical UTF-8 text and agrees
    # with Python, while comparing the JSONB document for semantic consistency.
    assert verified(pg11_setup, ev, binding) is True


def test_real_unicode_c4_options_roundtrip_without_loss(example, pg11_setup):
    candidate, binding, _ = example
    changed = candidate.model_copy(deep=True)
    changed.demand.families[0].label = 'Science / Español / 日本語 / 😀'
    ev = create_evidence(changed, binding=binding)
    assert 'Español / 日本語 / 😀' in ev.canonical_json
    assert verified(pg11_setup, ev, binding) is True


@pytest.mark.parametrize('scope_field,changed_value', [
    ('organisation_uuid', 'other-uuid'),
    ('schedule_uuid', 'other-uuid'),
    ('source_revision', 2),
    ('source_grid_json_1_sha256', 'b'*64),
    ('c4_validated_teaching_sha256', 'b'*64),
])
def test_real_sql_refuses_cross_school_schedule_revision_or_review(example, pg11_setup, scope_field, changed_value):
    _, binding, ev = example
    changed = (str(uuid4()) if changed_value == 'other-uuid' else changed_value)
    refused(pg11_setup, ev, replace(binding, **{scope_field:changed}),
            'C11_WRONG_SCHOOL_SCHEDULE_OR_SOURCE')


def test_real_sql_refuses_wrong_checksum_even_if_jsonb_matches(example, pg11_setup):
    _, binding, ev = example
    refused(pg11_setup, replace(ev,sha256='f'*64), binding, 'C11_BYTE_HASH_MISMATCH')


def test_real_sql_refuses_wrong_utf8_byte_length(example, pg11_setup):
    _, binding, ev = example
    refused(pg11_setup, replace(ev,canonical_utf8_length=ev.canonical_utf8_length+1),
            binding, 'C11_CANONICAL_BYTE_LENGTH')


def test_real_sql_refuses_semantically_other_jsonb_for_the_same_hash(example, pg11_setup):
    _, binding, ev = example
    refused(pg11_setup, ev, binding, 'C11_JSONB_CONTENT_MISMATCH', raw_jsonb='{"injected":true}')


def test_real_sql_refuses_unknown_contract_even_if_rehashed(example, pg11_setup):
    _, binding, ev = example
    payload = json.loads(ev.canonical_json)
    payload['contract_version'] = 'unreviewed-contract'
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    bad = replace(ev, canonical_json=text, canonical_utf8_length=len(text.encode('utf-8')),
                  sha256=sha256(text.encode('utf-8')).hexdigest())
    refused(pg11_setup, bad, binding, 'C11_ENVELOPE_VERSION_OR_TYPE')


def test_real_sql_refuses_missing_evidence_instead_of_returning_null(example, pg11_setup):
    import psycopg
    _, binding, ev = example
    args = list(arguments(ev, binding));args[0] = None
    with psycopg.connect(pg11_setup['dsn']) as db:
        with pytest.raises(psycopg.Error, match='C11_MISSING_BOUND_EVIDENCE'):
            db.execute(CHECK_SQL, args)


def test_client_role_has_no_schema_or_function_execute_privilege(pg11_setup):
    import psycopg
    with psycopg.connect(pg11_setup['dsn']) as db:
        row = db.execute("""SELECT
          has_schema_privilege('grid_c11_guest','grid_c11','USAGE'),
          has_function_privilege('grid_c11_guest',
            'grid_c11.verify_options_evidence_v1(text,jsonb,text,integer,uuid,uuid,integer,text,text)',
            'EXECUTE')""").fetchone()
    assert row == (False,False)


def test_verified_real_c4_proposal_has_correct_original_source_binding(pg11_setup):
    from scripts.run_c4_probes import crossed_multi_occurrence_fixture
    from veni_grid_integration.c4_flexible_feedback import propose_c4

    request = crossed_multi_occurrence_fixture()
    result = propose_c4(request)
    assert result.status == 'PROPOSED_VALIDATED'
    assert result.review.preserved_compulsory_requests == 48
    assert result.preview_c2.event_count == 18
    candidate = AcceptedOptions(demand=request.current.source.demand, plan=result.proposed_o1)
    binding = SourceBinding(
        organisation_uuid=str(uuid4()),schedule_uuid=str(uuid4()),source_revision=1,
        source_grid_json_1_sha256=fingerprint(request.current.source),
        c4_validated_teaching_sha256=result.review.proposed_c2_candidate_sha256,
    )
    ev = create_evidence(candidate, binding=binding)
    assert len(candidate.plan.offerings) == 9
    assert verified(pg11_setup, ev, binding) is True
