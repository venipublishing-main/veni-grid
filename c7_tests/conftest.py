"""C7 REAL PostgreSQL integration fixtures: disposable GitHub PG17 only.

Never run against any hosted, active, staging or production Supabase database.
The exact database-name guard fires *before any DDL*. All identities are invented.
"""
from __future__ import annotations
import os
from pathlib import Path
from uuid import uuid4

import pytest

ROOT=Path(__file__).resolve().parents[1]
EXPECTED_DB='grid_c7_isolated'
TABLES=('organisations','memberships','schedules','schedule_grants',
        'accepted_versions','proposals','operations','audit_events')


def guarded_dsn() -> str:
    dsn=os.environ.get('GRID_C7_PG_DSN')
    if not dsn or os.environ.get('GRID_C7_DISPOSABLE_ONLY')!='YES':
        raise RuntimeError('C7 refuses database execution without explicit isolated test gate')
    # Do not trust the DSN alone: the real database name and superuser context
    # are checked on the first connection BEFORE any CREATE/INSERT statement.
    return dsn


@pytest.fixture(scope='session')
def pg_setup():
    import psycopg
    dsn=guarded_dsn()
    with psycopg.connect(dsn, autocommit=True, connect_timeout=10) as admin:
        db, role, version=admin.execute(
            'SELECT current_database(), current_user, current_setting(\'server_version_num\')::int'
        ).fetchone()
        if db != EXPECTED_DB or role != 'postgres' or version < 170000 or version >= 180000:
            raise RuntimeError(f'C7 refuses unsafe PostgreSQL target: database={db!r}, role={role!r}, major={version//10000}')
        for name in ('anon','authenticated','service_role'):
            # These are disposable role *imitations*, not actual Supabase roles.
            if not admin.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(name,)).fetchone():
                admin.execute(f'CREATE ROLE {name} NOLOGIN NOSUPERUSER NOBYPASSRLS')
        admin.execute('CREATE SCHEMA auth')
        admin.execute('CREATE TABLE auth.users (id uuid PRIMARY KEY)')
        # This is the actual unchanged C6 reviewed SQL, applied only here.
        sql=(ROOT/'db/review/c6_grid_private_schema.sql').read_text(encoding='utf-8')
        admin.execute(sql, prepare=False)
        yield {'dsn':dsn,'db':db,'version':version,'sql':sql}
    # No teardown needed: disposable GitHub postgres:17 container is discarded.


@pytest.fixture
def conn(pg_setup):
    import psycopg
    with psycopg.connect(pg_setup['dsn'], connect_timeout=10) as db:
        yield db
        db.rollback()


@pytest.fixture
def two_schools(conn):
    a,b=uuid4(),uuid4(); sid_a,sid_b=uuid4(),uuid4();user_a,user_b=uuid4(),uuid4()
    conn.cursor().executemany('INSERT INTO auth.users(id) VALUES(%s)',[(str(user_a),),(str(user_b),)])
    conn.cursor().executemany('INSERT INTO grid_private.organisations(id,display_name) VALUES(%s,%s)',
                     [(str(a),'Invented School Alpha'),(str(b),'Invented School Beta')])
    conn.cursor().executemany('''INSERT INTO grid_private.memberships(organisation_id,account_id,state,role)
                         VALUES(%s,%s,'ACTIVE','OWNER')''',[(str(a),str(user_a)),(str(b),str(user_b))])
    conn.cursor().executemany('''INSERT INTO grid_private.schedules
                      (organisation_id,id,kind,label,head_revision,head_sha256)
                      VALUES (%s,%s,'ACADEMIC_OPTIONS',%s,1,%s)''',
                     [(str(a),str(sid_a),'Invented Alpha Options','a'*64),
                      (str(b),str(sid_b),'Invented Beta Options','b'*64)])
    conn.cursor().executemany('''INSERT INTO grid_private.accepted_versions
                      (organisation_id,schedule_id,revision,snapshot,sha256,accepted_by)
                      VALUES (%s,%s,1,%s::jsonb,%s,%s)''',
                     [(str(a),str(sid_a),'{"version":1}','a'*64,str(user_a)),
                      (str(b),str(sid_b),'{"version":1}','b'*64,str(user_b))])
    return {'a':str(a),'b':str(b),'sa':str(sid_a),'sb':str(sid_b),
            'ua':str(user_a),'ub':str(user_b)}


def expect_sqlstate(db, sqlstate: str, sql: str, args=None):
    """Assert real PG exception in a nested SAVEPOINT, never poison test txn."""
    import psycopg
    with pytest.raises(psycopg.Error) as exc:
        with db.transaction():
            db.execute(sql,args)
    assert exc.value.sqlstate==sqlstate, (exc.value.sqlstate,str(exc.value)[:300])
