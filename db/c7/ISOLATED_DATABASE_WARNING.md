# Disposable PostgreSQL proof — never apply to the Veni staging project

The C7 GitHub workflow creates a temporary `postgres:17` service with a database
named `grid_c7_isolated`, synthetic `auth.users` entries, and temporary roles.
The service **does not match a real Supabase schema**. Its sole purpose is to
execute and negatively test the exact C6 private Grid review SQL on PostgreSQL.

`c7_tests/conftest.py` refuses all unexpected database names, executing roles,
PostgreSQL versions, or missing explicit disposable confirmation. The test
never downloads production data, queries a hosted project, applies real
migrations, creates an approval API or changes an existing timetable.

The C6 schema remains at `db/review/c6_grid_private_schema.sql`, not under
`supabase/migrations`. A live database writer / RLS allow-policy / user session
integration must be separately designed and executed against an authorised
staging clone after a migration-history review.
