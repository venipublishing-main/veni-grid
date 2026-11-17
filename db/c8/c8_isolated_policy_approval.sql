-- C8 EXPERIMENTAL ISOLATED-ONLY SQL; NEVER a Veni Supabase migration.
-- Must be applied AFTER the unchanged C6 grid_private DDL, on a disposable
-- postgres:17 service named EXACTLY grid_c8_isolated by postgres superuser.
-- The server-side actor/AAL settings below are NOT authentication. Only an
-- independently verified server process could set them in production.
DO $gate$
BEGIN
  IF current_database() <> 'grid_c8_isolated' OR current_user <> 'postgres'
     OR current_setting('server_version_num')::int < 170000
     OR current_setting('server_version_num')::int >= 180000 THEN
    RAISE EXCEPTION 'C8_DISPOSABLE_DATABASE_ONLY';
  END IF;
END $gate$;

BEGIN;
CREATE ROLE grid_c8_reader NOLOGIN NOSUPERUSER NOBYPASSRLS;
CREATE ROLE grid_c8_operator NOLOGIN NOSUPERUSER NOBYPASSRLS;
CREATE ROLE grid_c8_writer NOLOGIN NOSUPERUSER NOBYPASSRLS;
GRANT USAGE ON SCHEMA grid_private TO grid_c8_reader,grid_c8_operator,grid_c8_writer;

-- The reader is server-only, never directly reachable via PostgREST.
-- Note: custom settings are writable by a PostgreSQL connection holder.
-- Thus no client role can inherit or SET ROLE to grid_c8_reader/operator.
CREATE FUNCTION grid_private.c8_actor() RETURNS uuid
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = '' AS $$
  SELECT nullif(current_setting('grid.c8_actor_id',true),'')::uuid;
$$;
REVOKE EXECUTE ON FUNCTION grid_private.c8_actor() FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION grid_private.c8_actor() TO grid_c8_reader,grid_c8_writer;

GRANT SELECT ON grid_private.memberships,grid_private.schedules,
  grid_private.schedule_grants,grid_private.accepted_versions,
  grid_private.proposals,grid_private.audit_events TO grid_c8_reader;

CREATE POLICY c8_member_self ON grid_private.memberships FOR SELECT TO grid_c8_reader
USING (account_id = (SELECT grid_private.c8_actor()) AND state='ACTIVE');
CREATE POLICY c8_grant_self ON grid_private.schedule_grants FOR SELECT TO grid_c8_reader
USING (account_id=(SELECT grid_private.c8_actor()) AND EXISTS (
 SELECT 1 FROM grid_private.memberships m
 WHERE m.organisation_id=schedule_grants.organisation_id
   AND m.account_id=(SELECT grid_private.c8_actor()) AND m.state='ACTIVE'
));
CREATE POLICY c8_schedule_view ON grid_private.schedules FOR SELECT TO grid_c8_reader
USING (EXISTS (
 SELECT 1 FROM grid_private.memberships m
 WHERE m.organisation_id=schedules.organisation_id
  AND m.account_id=(SELECT grid_private.c8_actor()) AND m.state='ACTIVE'
  AND (m.role='OWNER' OR EXISTS (
    SELECT 1 FROM grid_private.schedule_grants g
    WHERE g.organisation_id=schedules.organisation_id
      AND g.schedule_id=schedules.id
      AND g.account_id=(SELECT grid_private.c8_actor())
      AND g.permission='view'
  ))
));
CREATE POLICY c8_version_view ON grid_private.accepted_versions FOR SELECT TO grid_c8_reader
USING (EXISTS (SELECT 1 FROM grid_private.schedules s
 WHERE s.organisation_id=accepted_versions.organisation_id
 AND s.id=accepted_versions.schedule_id));
CREATE POLICY c8_proposal_view ON grid_private.proposals FOR SELECT TO grid_c8_reader
USING (EXISTS (SELECT 1 FROM grid_private.schedules s
 WHERE s.organisation_id=proposals.organisation_id
 AND s.id=proposals.schedule_id));
CREATE POLICY c8_audit_view ON grid_private.audit_events FOR SELECT TO grid_c8_reader
USING (EXISTS (SELECT 1 FROM grid_private.schedules s
 WHERE s.organisation_id=audit_events.organisation_id
 AND s.id=audit_events.schedule_id));

-- The **only** role that executes the private approval function is the
-- server operator. It has no direct TABLE privileges. This SQL does not
-- expose any direct client API, membership provisioner or proposal stager.
GRANT SELECT,INSERT,UPDATE ON grid_private.organisations,
 grid_private.memberships,grid_private.schedules,grid_private.schedule_grants,
 grid_private.accepted_versions,grid_private.proposals,grid_private.operations,
 grid_private.audit_events TO grid_c8_writer;
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA grid_private TO grid_c8_writer;
DO $writer_policy$
DECLARE t text;
BEGIN
 FOREACH t IN ARRAY ARRAY['organisations','memberships','schedules',
   'schedule_grants','accepted_versions','proposals','operations','audit_events']
 LOOP
  EXECUTE format('CREATE POLICY c8_writer_allowed ON grid_private.%I FOR ALL TO grid_c8_writer USING (true) WITH CHECK (true)',t);
 END LOOP;
END $writer_policy$;
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;
GRANT USAGE ON SCHEMA public TO grid_c8_writer;

-- A database reference for APPROVE only. A verified C4 proposal MUST have been
-- staged by a separate trusted process; this SQL does not accept arbitrary
-- client-supplied proposal evidence and does not verify solver validity.
-- The caller's actor/AAL settings are trusted ONLY because grid_c8_operator
-- may be assumed by the server connection; these are NOT live JWT checks.
CREATE FUNCTION grid_private.c8_approve(
 p_org uuid,p_schedule uuid,p_proposal uuid,
 p_expected_revision integer,p_expected_sha256 text,
 p_reason text,p_idempotency text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $body$
DECLARE
 actor uuid;
 s grid_private.schedules%ROWTYPE;
 p grid_private.proposals%ROWTYPE;
 op grid_private.operations%ROWTYPE;
 requesthash text;
 newrev integer;
 prev_hash text;
 eventhash text;
 outval jsonb;
BEGIN
 actor:=grid_private.c8_actor();
 IF actor IS NULL THEN RAISE EXCEPTION 'C8_IDENTITY_REQUIRED' USING ERRCODE='42501'; END IF;
 IF current_setting('grid.c8_aal',true) IS DISTINCT FROM 'aal2' THEN
   RAISE EXCEPTION 'C8_MFA_STEP_UP_REQUIRED' USING ERRCODE='42501';
 END IF;
 IF p_reason IS NULL OR length(btrim(p_reason)) < 8 OR
    p_idempotency IS NULL OR length(p_idempotency) NOT BETWEEN 8 AND 128 THEN
   RAISE EXCEPTION 'C8_REASON_OR_IDEMPOTENCY_REQUIRED' USING ERRCODE='22023';
 END IF;
 -- Separate live membership plus exact per-schedule grant (no email/entitlement).
 IF NOT EXISTS (SELECT 1 FROM grid_private.memberships m
     JOIN grid_private.schedule_grants g
      ON g.organisation_id=m.organisation_id AND g.account_id=m.account_id
     WHERE m.organisation_id=p_org AND m.account_id=actor AND m.state='ACTIVE'
      AND g.schedule_id=p_schedule AND g.permission='approve') THEN
   RAISE EXCEPTION 'C8_PERMISSION_DENIED' USING ERRCODE='42501';
 END IF;
 requesthash:=encode(public.digest(convert_to(
    pg_catalog.jsonb_build_object('proposal_id',p_proposal,
     'expected_revision',p_expected_revision,
     'expected_sha256',p_expected_sha256,
     'reason',btrim(p_reason))::text,'UTF8'),'sha256'),'hex');
 SELECT * INTO op FROM grid_private.operations o
   WHERE o.organisation_id=p_org AND o.schedule_id=p_schedule
    AND o.actor_id=actor AND o.operation='APPROVE'
    AND o.idempotency_key=p_idempotency;
 IF FOUND THEN
   IF op.request_sha256<>requesthash THEN
     RAISE EXCEPTION 'C8_IDEMPOTENCY_CONFLICT' USING ERRCODE='23505';
   END IF;
   RETURN op.response;
 END IF;
 SELECT * INTO s FROM grid_private.schedules sch
  WHERE sch.organisation_id=p_org AND sch.id=p_schedule FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'C8_SCHEDULE_NOT_FOUND' USING ERRCODE='42501'; END IF;
 IF s.head_revision<>p_expected_revision OR s.head_sha256<>p_expected_sha256 THEN
   RAISE EXCEPTION 'C8_STALE_SOURCE' USING ERRCODE='40001';
 END IF;
 IF s.kind<>'ACADEMIC_OPTIONS' THEN
   RAISE EXCEPTION 'C8_OPTIONS_ONLY' USING ERRCODE='42501';
 END IF;
 SELECT * INTO p FROM grid_private.proposals v
  WHERE v.organisation_id=p_org AND v.schedule_id=p_schedule
    AND v.id=p_proposal FOR UPDATE;
 IF NOT FOUND OR p.state<>'PENDING' THEN
   RAISE EXCEPTION 'C8_PROPOSAL_NOT_PENDING' USING ERRCODE='42501';
 END IF;
 IF p.proposed_by=actor THEN
   RAISE EXCEPTION 'C8_MAKER_CHECKER_REQUIRED' USING ERRCODE='42501';
 END IF;
 IF p.source_revision<>s.head_revision OR p.source_sha256<>s.head_sha256 THEN
   RAISE EXCEPTION 'C8_STALE_PROPOSAL' USING ERRCODE='40001';
 END IF;
 -- Detect accidental alteration of the frozen test fixture. Cryptographic
 -- integrity IS NOT independent O1/C2 solver validation.
 IF p.payload_sha256 <> encode(public.digest(convert_to(p.payload::text,'UTF8'),'sha256'),'hex') THEN
   RAISE EXCEPTION 'C8_PROPOSAL_HASH_MISMATCH' USING ERRCODE='23514';
 END IF;
 newrev:=s.head_revision+1;
 UPDATE grid_private.schedules SET head_revision=newrev,head_sha256=p.payload_sha256
 WHERE organisation_id=p_org AND id=p_schedule
   AND head_revision=p_expected_revision AND head_sha256=p_expected_sha256;
 IF NOT FOUND THEN RAISE EXCEPTION 'C8_STALE_SOURCE' USING ERRCODE='40001'; END IF;
 INSERT INTO grid_private.accepted_versions(
  organisation_id,schedule_id,revision,snapshot,sha256,parent_revision,
  source_proposal_id,accepted_by)
 VALUES(p_org,p_schedule,newrev,p.payload,p.payload_sha256,p_expected_revision,p_proposal,actor);
 UPDATE grid_private.proposals SET state='APPROVED',approved_revision=newrev
 WHERE organisation_id=p_org AND schedule_id=p_schedule AND id=p_proposal;
 SELECT a.event_sha256 INTO prev_hash FROM grid_private.audit_events a
 WHERE a.organisation_id=p_org AND a.schedule_id=p_schedule
 ORDER BY a.event_id DESC LIMIT 1;
 prev_hash:=coalesce(prev_hash,repeat('0',64));
 eventhash:=encode(public.digest(convert_to(
  prev_hash||p_org::text||p_schedule::text||p_proposal::text||actor::text||newrev::text||btrim(p_reason),
  'UTF8'),'sha256'),'hex');
 INSERT INTO grid_private.audit_events(
  organisation_id,schedule_id,actor_id,action,reason,before_revision,
  after_revision,previous_event_sha256,event_sha256,detail)
 VALUES(p_org,p_schedule,actor,'PROPOSAL_APPROVED',btrim(p_reason),
  p_expected_revision,newrev,prev_hash,eventhash,
  pg_catalog.jsonb_build_object('proposal_id',p_proposal,'scope','ACADEMIC_OPTIONS_ONLY'));
 outval:=pg_catalog.jsonb_build_object('status','APPROVED',
   'revision',newrev,'published_revision',s.published_revision,
   'scope','ACADEMIC_OPTIONS_ONLY','timetable_published',false);
 INSERT INTO grid_private.operations(organisation_id,schedule_id,actor_id,
   operation,idempotency_key,request_sha256,response)
 VALUES(p_org,p_schedule,actor,'APPROVE',p_idempotency,requesthash,outval);
 RETURN outval;
END $body$;
ALTER FUNCTION grid_private.c8_approve(uuid,uuid,uuid,integer,text,text,text)
 OWNER TO grid_c8_writer;
REVOKE ALL ON FUNCTION grid_private.c8_approve(uuid,uuid,uuid,integer,text,text,text)
 FROM PUBLIC,anon,authenticated,service_role,grid_c8_reader;
GRANT EXECUTE ON FUNCTION grid_private.c8_approve(uuid,uuid,uuid,integer,text,text,text)
 TO grid_c8_operator;

-- No LOGIN/INHERIT role grants from C8 to browser clients or untrusted users.
-- C8 approvals are not published to an app; there is no publish or rollback SQL API.
-- Grid Auth/JWKS and live membership must be connected before production use.
COMMIT;
