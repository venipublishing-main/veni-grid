"""C6 DDL REVIEW lint. These tests are NOT live PostgreSQL/RLS execution."""
from __future__ import annotations
from pathlib import Path
import re

SQL=(Path(__file__).resolve().parents[1]/'db/review/c6_grid_private_schema.sql').read_text()
TABLES=('organisations','memberships','schedules','schedule_grants',
        'accepted_versions','proposals','operations','audit_events')

def test_sql_is_unapplied_review_artifact_not_an_enabled_migration():
    assert 'UNAPPLIED REVIEW DDL' in SQL
    assert str(Path(__file__).resolve().parents[1]/'db/review').endswith('/db/review')
    assert SQL.strip().endswith('COMMIT;') and 'BEGIN;' in SQL

def test_all_grid_tables_are_isolated_in_one_private_schema():
    assert 'CREATE SCHEMA IF NOT EXISTS grid_private' in SQL
    for t in TABLES:
        assert f'CREATE TABLE grid_private.{t} (' in SQL
    assert not re.search(r'CREATE TABLE\s+(?:IF NOT EXISTS\s+)?public\.',SQL,re.I)

def test_all_tables_have_both_rls_enabled_and_forced():
    for t in TABLES:
        assert f'ALTER TABLE grid_private.{t} ENABLE ROW LEVEL SECURITY' in SQL
        assert f'ALTER TABLE grid_private.{t} FORCE ROW LEVEL SECURITY' in SQL
    assert SQL.count('ENABLE ROW LEVEL SECURITY')==len(TABLES)

def test_untrusted_supabase_roles_are_not_granted_direct_data_api_access():
    for s in ('REVOKE ALL ON SCHEMA grid_private FROM PUBLIC, anon, authenticated',
              'REVOKE ALL ON ALL TABLES IN SCHEMA grid_private FROM PUBLIC, anon, authenticated',
              'REVOKE ALL ON ALL SEQUENCES IN SCHEMA grid_private FROM PUBLIC, anon, authenticated',
              'ALTER DEFAULT PRIVILEGES IN SCHEMA grid_private REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated'):
        assert s in SQL
    # DDL is intentionally unusable from an end-user session until a separate security gate.
    assert not re.search(r'\bGRANT\s+(?:ALL|SELECT|INSERT|UPDATE|DELETE|USAGE|EXECUTE)\b',SQL,re.I)
    assert not re.search(r'CREATE POLICY\b',SQL,re.I)

def test_account_identity_is_central_supabase_uuid_and_never_email_matching():
    assert SQL.count('REFERENCES auth.users(id)')>=2
    assert 'CREATE TABLE grid_private.memberships' in SQL
    assert 'account_id uuid' in SQL
    assert 'email text' not in SQL.lower()

def test_every_schedule_and_revision_uses_composite_tenant_foreign_key():
    for t in ('schedule_grants','accepted_versions','proposals','operations','audit_events'):
        section=SQL.split(f'CREATE TABLE grid_private.{t} (',1)[1].split('CREATE TABLE grid_private.',1)[0]
        assert 'FOREIGN KEY (organisation_id,schedule_id) REFERENCES grid_private.schedules(organisation_id,id)' in section
    assert 'FOREIGN KEY (organisation_id,account_id) REFERENCES grid_private.memberships' in SQL

def test_independent_timetable_kinds_are_explicit():
    for label in ['ACADEMIC_OPTIONS','ACADEMIC_LESSONS','EXAMINATIONS','INVIGILATION','DUTIES','SPORT','ROOMS']:
        assert f"'{label}'" in SQL

def test_mutation_history_has_declared_database_level_immutability():
    assert 'grid_versions_immutable BEFORE UPDATE OR DELETE ON grid_private.accepted_versions' in SQL
    assert 'grid_audit_immutable BEFORE UPDATE OR DELETE ON grid_private.audit_events' in SQL
    assert 'grid_proposal_content_immutable BEFORE UPDATE ON grid_private.proposals' in SQL
    assert 'LANGUAGE plpgsql SECURITY INVOKER SET search_path' in SQL
    assert not re.search(r'^\s*(?:CREATE\s+FUNCTION|LANGUAGE).*SECURITY DEFINER', SQL, re.I | re.M)

def test_composite_idempotency_keys_and_audit_reasons():
    assert 'PRIMARY KEY(organisation_id,schedule_id,actor_id,operation,idempotency_key)' in SQL
    assert 'CHECK (length(trim(reason)) >= 8)' in SQL
    assert 'previous_event_sha256 text NOT NULL' in SQL
    assert 'event_sha256 text NOT NULL' in SQL

def test_no_public_principal_claims_or_exposed_approval_rpc_created():
    assert 'auth.uid()' not in SQL
    assert 'request.jwt.claim' not in SQL
    assert not re.search(r'CREATE FUNCTION\s+public\.',SQL,re.I)
    assert 'NO browser RLS policies' in SQL
