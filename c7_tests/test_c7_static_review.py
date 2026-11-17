"""Guard new C7 artifacts; actual database tests are in test_c7_postgres.py."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SQL=(ROOT/'db/review/c6_grid_private_schema.sql').read_text(encoding='utf-8')
WF=(ROOT/'.github/workflows/c7-isolated-postgres.yml').read_text(encoding='utf-8')


def test_c6_unapplied_review_source_unmodified():
    assert SQL.startswith('-- VENI GRID C6 — UNAPPLIED REVIEW DDL')
    assert 'BEGIN;' in SQL and SQL.rstrip().endswith('COMMIT;')


def test_c7_targets_only_disposable_postgres17():
    assert 'postgres:17' in WF
    assert 'grid_c7_isolated' in WF
    assert 'GRID_C7_DISPOSABLE_ONLY: "YES"' in WF
    assert '--remote' not in WF


def test_c7_no_live_supabase_or_public_api_change():
    assert 'supabase db push' not in WF
    assert 'supabase apply_migration' not in WF
    assert 'deploy' not in WF.lower()


def test_c7_has_a_required_real_pg_python_test():
    a=(ROOT/'c7_tests/test_c7_postgres.py').read_text(encoding='utf-8')
    assert 'psycopg' in a and 'test_simultaneous_postgres_compare_and_swap_only_one_wins' in a
    assert 'test_accidental_select_grant_still_yields_zero_rows_from_rls' in a
