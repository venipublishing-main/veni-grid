"""C8 test-source guards run locally and in GitHub. They aren't live PG evidence."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SQL=(ROOT/'db/c8/c8_isolated_policy_approval.sql').read_text()
WF=(ROOT/'.github/workflows/c8-isolated-approval.yml').read_text()

def test_disposable_guards_and_no_supabase_migrations():
    assert "grid_c8_isolated" in SQL and "C8_DISPOSABLE_DATABASE_ONLY" in SQL
    assert "GRID_C8_DISPOSABLE_ONLY" in WF and "postgres:17" in WF
    assert 'supabase db push' not in WF and 'apply_migration' not in WF
    assert (ROOT/'db/review/c6_grid_private_schema.sql').exists()

def test_server_only_roles_never_public_api():
    for x in ('grid_c8_reader NOLOGIN','grid_c8_operator NOLOGIN','grid_c8_writer NOLOGIN'):
        assert x in SQL
    assert 'GRANT EXECUTE ON FUNCTION grid_private.c8_approve' in SQL
    assert 'TO grid_c8_operator' in SQL
    assert 'TO authenticated' not in SQL and 'TO anon' not in SQL
    assert 'SECURITY DEFINER SET search_path = \'\'' in SQL

def test_explicit_security_checks_anti_pretend():
    for s in ('C8_PERMISSION_DENIED','C8_MFA_STEP_UP_REQUIRED','C8_MAKER_CHECKER_REQUIRED',
              'C8_STALE_SOURCE','C8_IDEMPOTENCY_CONFLICT','C8_PROPOSAL_HASH_MISMATCH'):
        assert s in SQL
    assert 'APPROVED' in SQL and 'timetable_published' in SQL
    assert 'this SQL does not accept arbitrary' in SQL or 'does not accept arbitrary' in SQL

def test_no_modified_c7_or_identity_runtime():
    assert 'c8_tests' in WF
    assert '683' in WF
    assert 'supabase.co' not in WF
