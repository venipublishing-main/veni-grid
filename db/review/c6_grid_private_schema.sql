-- VENI GRID C6 — UNAPPLIED REVIEW DDL, not a production migration.
-- Requires a reviewed shared Veni Account Supabase PostgreSQL project. The
-- connected staging project is INACTIVE at authoring time: this SQL was NOT run.
-- One auth.users identity; Grid tenant/schedule authorisation is separate.
-- Private schema is deliberately NOT in the Supabase Data API exposed schemas.
-- No untrusted client role receives access and no write RPC is exposed.
BEGIN;
CREATE SCHEMA IF NOT EXISTS grid_private;
REVOKE ALL ON SCHEMA grid_private FROM PUBLIC, anon, authenticated;

CREATE TABLE grid_private.organisations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 display_name text NOT NULL CHECK (length(trim(display_name)) BETWEEN 2 AND 160),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE grid_private.memberships (
 organisation_id uuid NOT NULL REFERENCES grid_private.organisations(id),
 account_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
 state text NOT NULL CHECK (state IN ('ACTIVE','REVOKED')),
 role text NOT NULL CHECK (role IN ('OWNER','MEMBER')),
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (organisation_id, account_id)
);
CREATE INDEX grid_memberships_by_account ON grid_private.memberships(account_id, state);

CREATE TABLE grid_private.schedules (
 organisation_id uuid NOT NULL REFERENCES grid_private.organisations(id),
 id uuid NOT NULL DEFAULT gen_random_uuid(),
 kind text NOT NULL CHECK (kind IN ('ACADEMIC_OPTIONS','ACADEMIC_LESSONS','EXAMINATIONS','INVIGILATION','DUTIES','SPORT','ROOMS')),
 label text NOT NULL CHECK (length(trim(label)) BETWEEN 2 AND 160),
 head_revision integer NOT NULL DEFAULT 1 CHECK (head_revision >= 1),
 head_sha256 text NOT NULL CHECK (head_sha256 ~ '^[0-9a-f]{64}$'),
 published_revision integer CHECK (published_revision IS NULL OR published_revision <= head_revision),
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (organisation_id, id),
 UNIQUE (organisation_id, kind, label)
);
CREATE INDEX grid_schedules_kind ON grid_private.schedules(organisation_id,kind);

CREATE TABLE grid_private.schedule_grants (
 organisation_id uuid NOT NULL,
 schedule_id uuid NOT NULL,
 account_id uuid NOT NULL,
 permission text NOT NULL CHECK (permission IN ('view','propose','approve','publish','restore')),
 granted_by uuid NOT NULL REFERENCES auth.users(id),
 granted_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (organisation_id, schedule_id, account_id, permission),
 FOREIGN KEY (organisation_id,schedule_id) REFERENCES grid_private.schedules(organisation_id,id),
 FOREIGN KEY (organisation_id,account_id) REFERENCES grid_private.memberships(organisation_id,account_id)
);
CREATE INDEX grid_grants_by_account ON grid_private.schedule_grants(account_id,organisation_id,schedule_id);

CREATE TABLE grid_private.accepted_versions (
 organisation_id uuid NOT NULL,
 schedule_id uuid NOT NULL,
 revision integer NOT NULL CHECK (revision >= 1),
 snapshot jsonb NOT NULL,
 sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
 parent_revision integer,
 source_proposal_id uuid,
 accepted_by uuid NOT NULL,
 accepted_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (organisation_id,schedule_id,revision),
 FOREIGN KEY (organisation_id,schedule_id) REFERENCES grid_private.schedules(organisation_id,id),
 FOREIGN KEY (organisation_id,accepted_by) REFERENCES grid_private.memberships(organisation_id,account_id),
 CHECK (parent_revision IS NULL OR parent_revision < revision)
);

CREATE TABLE grid_private.proposals (
 organisation_id uuid NOT NULL,
 schedule_id uuid NOT NULL,
 id uuid NOT NULL DEFAULT gen_random_uuid(),
 source_revision integer NOT NULL CHECK (source_revision >= 1),
 source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
 payload jsonb NOT NULL,
 payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
 state text NOT NULL DEFAULT 'PENDING' CHECK (state IN ('PENDING','APPROVED','REJECTED')),
 proposed_by uuid NOT NULL,
 approved_revision integer,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (organisation_id,schedule_id,id),
 FOREIGN KEY (organisation_id,schedule_id) REFERENCES grid_private.schedules(organisation_id,id),
 FOREIGN KEY (organisation_id,proposed_by) REFERENCES grid_private.memberships(organisation_id,account_id),
 FOREIGN KEY (organisation_id,schedule_id,source_revision)
   REFERENCES grid_private.accepted_versions(organisation_id,schedule_id,revision)
);
CREATE INDEX grid_proposals_pending ON grid_private.proposals(organisation_id,schedule_id,state,source_revision);

CREATE TABLE grid_private.operations (
 organisation_id uuid NOT NULL,
 schedule_id uuid NOT NULL,
 actor_id uuid NOT NULL,
 operation text NOT NULL,
 idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 8 AND 128),
 request_sha256 text NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
 response jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(organisation_id,schedule_id,actor_id,operation,idempotency_key),
 FOREIGN KEY (organisation_id,schedule_id) REFERENCES grid_private.schedules(organisation_id,id),
 FOREIGN KEY (organisation_id,actor_id) REFERENCES grid_private.memberships(organisation_id,account_id)
);

CREATE TABLE grid_private.audit_events (
 event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 organisation_id uuid NOT NULL,
 schedule_id uuid NOT NULL,
 actor_id uuid NOT NULL, -- history survives membership deletion, pending retention policy
 action text NOT NULL,
 reason text NOT NULL CHECK (length(trim(reason)) >= 8),
 before_revision integer,
 after_revision integer,
 previous_event_sha256 text NOT NULL CHECK (previous_event_sha256 ~ '^[0-9a-f]{64}$'),
 event_sha256 text NOT NULL CHECK (event_sha256 ~ '^[0-9a-f]{64}$'),
 detail jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY (organisation_id,schedule_id) REFERENCES grid_private.schedules(organisation_id,id)
);
CREATE INDEX grid_audit_by_schedule ON grid_private.audit_events(organisation_id,schedule_id,event_id);

-- Defense in depth: any future misconfigured API grant remains default DENY.
ALTER TABLE grid_private.organisations ENABLE ROW LEVEL SECURITY;
ALTER TABLE grid_private.memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE grid_private.schedules ENABLE ROW LEVEL SECURITY;
ALTER TABLE grid_private.schedule_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE grid_private.accepted_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE grid_private.proposals ENABLE ROW LEVEL SECURITY;
ALTER TABLE grid_private.operations ENABLE ROW LEVEL SECURITY;
ALTER TABLE grid_private.audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE grid_private.organisations FORCE ROW LEVEL SECURITY;
ALTER TABLE grid_private.memberships FORCE ROW LEVEL SECURITY;
ALTER TABLE grid_private.schedules FORCE ROW LEVEL SECURITY;
ALTER TABLE grid_private.schedule_grants FORCE ROW LEVEL SECURITY;
ALTER TABLE grid_private.accepted_versions FORCE ROW LEVEL SECURITY;
ALTER TABLE grid_private.proposals FORCE ROW LEVEL SECURITY;
ALTER TABLE grid_private.operations FORCE ROW LEVEL SECURITY;
ALTER TABLE grid_private.audit_events FORCE ROW LEVEL SECURITY;

REVOKE ALL ON ALL TABLES IN SCHEMA grid_private FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA grid_private FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA grid_private FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA grid_private REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA grid_private REVOKE ALL ON SEQUENCES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA grid_private REVOKE ALL ON FUNCTIONS FROM PUBLIC, anon, authenticated;

-- Historical records are never modified in-place through ordinary SQL.
CREATE FUNCTION grid_private.reject_immutable_change() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN RAISE EXCEPTION 'Immutable Grid history: create a new revision' USING ERRCODE='23514'; END;
$$;
CREATE TRIGGER grid_versions_immutable BEFORE UPDATE OR DELETE ON grid_private.accepted_versions
FOR EACH ROW EXECUTE FUNCTION grid_private.reject_immutable_change();
CREATE TRIGGER grid_audit_immutable BEFORE UPDATE OR DELETE ON grid_private.audit_events
FOR EACH ROW EXECUTE FUNCTION grid_private.reject_immutable_change();
CREATE FUNCTION grid_private.protect_proposal_content() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
 IF OLD.payload IS DISTINCT FROM NEW.payload OR OLD.payload_sha256 IS DISTINCT FROM NEW.payload_sha256
    OR OLD.source_revision IS DISTINCT FROM NEW.source_revision
    OR OLD.source_sha256 IS DISTINCT FROM NEW.source_sha256
    OR OLD.proposed_by IS DISTINCT FROM NEW.proposed_by THEN
  RAISE EXCEPTION 'Immutable proposal content' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER grid_proposal_content_immutable BEFORE UPDATE ON grid_private.proposals
FOR EACH ROW EXECUTE FUNCTION grid_private.protect_proposal_content();
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA grid_private FROM PUBLIC, anon, authenticated;

-- NO browser RLS policies; NO GRANTs; NO SECURITY DEFINER APIs; NO service_role
-- bypass. A future *separate, reviewed* migration must grant only a constrained
-- server role and provide signed-session actor context after proven verification.
-- This is not a complete approval/publish transaction implementation.
COMMIT;
