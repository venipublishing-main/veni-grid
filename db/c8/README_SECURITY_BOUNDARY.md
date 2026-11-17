# C8 SQL — isolated disposable PG17 execution ONLY

`c8_isolated_policy_approval.sql` is intentionally **not** in `supabase/migrations`.

It can be executed only on `grid_c8_isolated` as PostgreSQL 17 `postgres`, after the C6 reviewed `grid_private` schema, and only with **invented identities**. The SQL adds three NOLOGIN, NOSUPERUSER, NOBYPASSRLS test roles, positive read-only RLS policies, and a restricted standalone APPROVE reference function. It does **not** implement a production authentication service, client Data API, stage verifier, publish/rollback API or actual Supabase Auth integration.

Warning: **PostgreSQL custom GUC context is client-settable by anyone holding the database connection**. The C8 actor and AAL settings cannot be accepted from untrusted client code. A real production integration must set those values only after the C6 live signed-token/session/MFA gates succeed on a trusted server, and must keep the operator role entirely inaccessible to clients. This is a database transaction *reference*, not production authority.
