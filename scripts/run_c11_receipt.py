"""Rebuild one C4 options witness and prove C11 UTF-8 digest on disposable PG17.

This executes no DDL or writes to the database. Only the ignored local receipt
is saved; no credentials, users, timetable approval or hosted resources.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from scripts.run_c4_probes import crossed_multi_occurrence_fixture
from veni_grid_authority.c11_evidence import SourceBinding, create_evidence, verify_evidence
from veni_grid_contract.handoff_common import fingerprint
from veni_grid_contract.options_handoff import AcceptedOptions
from veni_grid_integration.c4_flexible_feedback import propose_c4, review_errors

ROOT = Path(__file__).resolve().parents[1]


def run():
    import psycopg
    from psycopg.conninfo import conninfo_to_dict

    dsn = os.environ.get('GRID_C11_PG_DSN', '')
    if os.environ.get('GRID_C11_DISPOSABLE_ONLY') != 'YES' or not dsn:
        raise RuntimeError('C11 receipt requires disposable PG17 gate')
    conninfo = conninfo_to_dict(dsn)
    if (conninfo.get('dbname') != 'grid_c11_isolated' or
        conninfo.get('host') not in ('localhost','127.0.0.1') or
        conninfo.get('hostaddr') not in (None, '127.0.0.1') or
        conninfo.get('user') != 'postgres'):
        raise RuntimeError('C11 receipt refuses unexpected database target')

    request = crossed_multi_occurrence_fixture()
    result = propose_c4(request)
    if (result.status != 'PROPOSED_VALIDATED' or
        review_errors(request.current,result.proposed_o1,result.preview_c2,result.review)):
        raise RuntimeError('C4 did not generate an independently reviewed proposal')
    candidate = AcceptedOptions(demand=request.current.source.demand, plan=result.proposed_o1)
    binding = SourceBinding(
        organisation_uuid=str(uuid4()), schedule_uuid=str(uuid4()), source_revision=1,
        source_grid_json_1_sha256=fingerprint(request.current.source),
        c4_validated_teaching_sha256=result.review.proposed_c2_candidate_sha256,
    )
    evidence = create_evidence(candidate, binding=binding)
    if verify_evidence(evidence, binding=binding) != candidate:
        raise RuntimeError('C11 Python verifier disagrees with source candidate')

    with psycopg.connect(dsn,connect_timeout=8) as db:
        name, role, version = db.execute(
            "SELECT current_database(),current_user,current_setting('server_version_num')::int"
        ).fetchone()
        if name != 'grid_c11_isolated' or role != 'postgres' or not 170000 <= version < 180000:
            raise RuntimeError('C11 receipt refuses wrong PG service')
        checked, pgsha, jsonbhash = db.execute("""SELECT
            grid_c11.verify_options_evidence_v1(%s::text,%s::jsonb,%s::text,%s::integer,
              %s::uuid,%s::uuid,%s::integer,%s::text,%s::text),
            encode(public.digest(convert_to(%s::text,'UTF8'),'sha256'),'hex'),
            encode(public.digest(convert_to((%s::jsonb)::text,'UTF8'),'sha256'),'hex')""",(
                evidence.canonical_json,evidence.canonical_json,evidence.sha256,
                evidence.canonical_utf8_length,binding.organisation_uuid,
                binding.schedule_uuid,binding.source_revision,
                binding.source_grid_json_1_sha256,binding.c4_validated_teaching_sha256,
                evidence.canonical_json,evidence.canonical_json)).fetchone()
        if not checked or pgsha != evidence.sha256 or jsonbhash == evidence.sha256:
            raise RuntimeError('Canonical Python/PG17 parity evidence failed')

    receipt = {
        'kind': 'C11_VERSIONED_EXACT_UTF8_POSTGRES_REFERENCE',
        'contract_version': evidence.contract_version,
        'serializer': evidence.serializer,
        'executed_real_postgresql': True,
        'postgresql_major': version // 10000,
        'python_bytes_equal_pg_digest': True,
        'postgres_jsonb_text_digest_differs': True,
        'sha256': evidence.sha256,
        'utf8_byte_length': evidence.canonical_utf8_length,
        'source_revision': binding.source_revision,
        'compulsory_requests_preserved': len(candidate.plan.allocations),
        'proposed_sections': len(candidate.plan.offerings),
        'independently_validated_teaching_events': result.preview_c2.event_count,
        'candidate_hard_validated': result.preview_c2.independent_hard_validation == 'PASSED',
        'proposal_approval': 'NOT_GRANTED',
        'publication': 'NOT_GRANTED',
        'hosted_supabase_migration': 'NOT_APPLIED',
        'real_school_data': 'NONE',
        'account_integration': 'DEFERRED',
    }
    output = ROOT / 'c11-output'
    output.mkdir(exist_ok=True)
    (output / 'c11-byte-parity-receipt.json').write_text(
        json.dumps(receipt,indent=2,ensure_ascii=False) + '\n',encoding='utf-8')
    print(json.dumps(receipt,indent=2,ensure_ascii=False))
    return receipt


if __name__ == '__main__':
    run()
