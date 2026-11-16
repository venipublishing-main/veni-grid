"""Execute and explain C7 evidence from a REAL, disposable PostgreSQL 17 DB.

NEVER target actual Supabase, real school records or a persistent database.
The GitHub service is discarded automatically. No secret, token, DSN or user ID
is written to the output files.
"""
from __future__ import annotations
import os, json, html
from pathlib import Path
from uuid import uuid4
import psycopg

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'c7-output'
TABLES=('organisations','memberships','schedules','schedule_grants',
        'accepted_versions','proposals','operations','audit_events')


def run() -> dict:
    dsn=os.environ.get('GRID_C7_PG_DSN')
    if os.environ.get('GRID_C7_DISPOSABLE_ONLY')!='YES' or not dsn:
        raise RuntimeError('C7 requires explicit disposable PostgreSQL environment')
    OUT.mkdir(parents=True,exist_ok=True)
    with psycopg.connect(dsn) as db:
        name,actor,version=db.execute("SELECT current_database(), current_user, current_setting('server_version_num')::int").fetchone()
        if name!='grid_c7_isolated' or actor!='postgres' or not 170000 <= version < 180000:
            raise RuntimeError('C7 refuses any unexpected database or role')
        rows=db.execute("""SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='grid_private' AND c.relkind='r' ORDER BY c.relname""").fetchall()
        assert {r[0] for r in rows}==set(TABLES) and all(r[1] and r[2] for r in rows)
        no_clients=all(not db.execute("SELECT has_schema_privilege(%s,'grid_private','USAGE')",(role,)).fetchone()[0]
                       for role in ('anon','authenticated','service_role'))
        assert no_clients
        count=db.execute("SELECT count(*) FROM pg_policies WHERE schemaname='grid_private'").fetchone()[0]
        assert count==0
        # Each proof is independently executed here, not merely copied from pytest.
        org,sid=str(uuid4()),str(uuid4())
        db.execute('INSERT INTO grid_private.organisations(id,display_name) VALUES(%s,%s)',(org,'Disposable demonstration'))
        db.execute("INSERT INTO grid_private.schedules(organisation_id,id,kind,label,head_revision,head_sha256) VALUES(%s,%s,'ACADEMIC_OPTIONS','Synthetic option history',1,%s)",(org,sid,'a'*64))
        update="UPDATE grid_private.schedules SET head_revision=2,head_sha256=%s WHERE organisation_id=%s AND id=%s AND head_revision=1 AND head_sha256=%s"
        first=db.execute(update,('b'*64,org,sid,'a'*64)).rowcount
        stale=db.execute(update,('c'*64,org,sid,'a'*64)).rowcount
        assert first==1 and stale==0
        # Accidental GRANT remains safe because every table is FORCE RLS with
        # zero policies: signed-in role sees no schedules at all.
        db.execute('GRANT USAGE ON SCHEMA grid_private TO authenticated')
        db.execute('GRANT SELECT ON grid_private.schedules TO authenticated')
        db.execute('SAVEPOINT c7_probe_grants')
        db.execute('SET LOCAL ROLE authenticated')
        visible=db.execute('SELECT count(*) FROM grid_private.schedules').fetchone()[0]
        db.execute('ROLLBACK TO SAVEPOINT c7_probe_grants')
        db.execute('RELEASE SAVEPOINT c7_probe_grants')
        assert visible==0
        db.rollback()  # Discard seed and accidental-grant experiment.
    record={
      'kind':'C7_EXECUTED_DISPOSABLE_POSTGRESQL_GATE',
      'postgresql_major':17,'database':'GRID_C7_ISOLATED_ONLY',
      'executed_real_postgresql':True,
      'live_veni_supabase_changed':False,
      'central_account_fixture':'MINIMAL_DISPOSABLE_AUTH_USERS_STUB',
      'private_tables_checked':len(TABLES),
      'rls_enabled_and_forced':True,
      'direct_client_schema_access':'DENIED',
      'direct_anon_authenticated_service_grants':'NONE',
      'rls_policies_in_schema':0,
      'accidental_authenticated_select_grant_rows_visible':visible,
      'revision_cas_first_write':first,
      'revision_cas_stale_second_write':stale,
      'runtime_tenant_permission_policies':'NOT_IMPLEMENTED',
      'real_jwt_sessions':'NOT_CONNECTED',
      'real_approval_transaction':'NOT_CONNECTED',
      'migration_history':'NOT_CREATED',
      'production_publication':'NOT_GRANTED',
      'disposable_database_writes':'ROLLED_BACK_OR_DISCARDED'
    }
    (OUT/'c7-postgresql-receipt.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    details=[
       ('PostgreSQL 17 executed','The security SQL was parsed and applied by a real isolated PostgreSQL service.'),
       ('Eight Grid tables protected','Each table has RLS enabled and FORCE RLS. No browser role was granted access.'),
       ('Extra permission did not expose rows','Even with a temporary accidental SELECT grant, the signed-in test role saw zero schedules.'),
       ('Concurrent revision safety','An update with the correct version succeeded; the stale compare-and-swap update changed zero records.'),
       ('School boundaries','Composite tenant/schedule foreign keys and immutable history have separate real-database negative tests.'),
       ('Not yet production','There is no live Veni Account integration, real school membership registry, privileged approval API or actual Supabase migration.')
    ]
    cards=''.join('<article><h3>'+html.escape(name)+'</h3><p>'+html.escape(explain)+'</p></article>' for name,explain in details)
    page=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Veni Grid C7 — PostgreSQL security test</title><style>
      body{{background:#f4f7fa;margin:0;color:#183049;font-family:Inter,system-ui,Arial,sans-serif}}header{{background:#172d46;color:white;padding:35px max(20px,calc((100vw - 1120px)/2))}}h1{{font-size:clamp(25px,3vw,39px);margin:8px 0}}header p{{color:#c1cfd9;max-width:760px;line-height:1.6}}
      main{{padding:22px;max-width:1120px;margin:auto}}.key{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-bottom:22px}}.metric,article{{border:1px solid #dbe5ee;border-radius:13px;padding:21px;background:white}}.metric strong{{display:block;font-size:31px}}.metric small{{color:#647b8d}}.details{{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}}h3{{margin:0 0 8px;font-size:17px}}article p{{color:#536b80;font-size:13px;line-height:1.7}}.warn{{border-left:4px solid #ac754b;background:#fff5e9;margin:20px 0;padding:17px;border-radius:12px;line-height:1.7;font-size:13px}}footer{{font-size:12px;color:#667e8f;line-height:1.7}}@media(max-width:650px){{.key,.details{{grid-template-columns:1fr}}}}
      </style></head><body><header><small>VENI GRID / DATABASE SECURITY</small><h1>What did PostgreSQL actually block?</h1><p>A real database test, performed only on an invented school and a disposable Postgres 17 instance—not the Veni website or real school data.</p></header><main><div class="key"><div class="metric"><strong>8/8</strong><small>Private tables RLS-protected</small></div><div class="metric"><strong>0</strong><small>Rows exposed after accidental client grant</small></div><div class="metric"><strong>0</strong><small>Stale revision changes accepted</small></div></div><div class="details">{cards}</div><div class="warn"><b>Still not live:</b> a real authenticated school administrator, actual school membership permissions, runtime authorisation policies, and approved PostgreSQL write/publish transactions have not been connected. This test cannot replace staging security review, backups, or penetration testing.</div><footer>Evidence is produced by an actual disposable PostgreSQL test process; credentials and example identities are not included in this report. Existing Grid timetables are unchanged.</footer></main></body></html>'''
    (OUT/'c7-postgresql-explained.html').write_text(page,encoding='utf-8')
    print(json.dumps(record,indent=2))
    return record

if __name__=='__main__':
    run()
