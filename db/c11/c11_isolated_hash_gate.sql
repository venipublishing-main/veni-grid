-- C11 REVIEW ONLY. NOT a Supabase migration and NOT an approval function.
-- The function verifies SHA-256 on exact Python GRID-JSON-1 UTF-8 bytes,
-- then checks the corresponding JSONB semantics and server-selected scope.
-- PostgreSQL JSONB::text is deliberately NEVER treated as canonical bytes.
DO $gate$
BEGIN
  IF current_database() <> 'grid_c11_isolated'
     OR current_user <> 'postgres'
     OR current_setting('server_version_num')::int NOT BETWEEN 170000 AND 179999
     OR current_setting('grid.c11_disposable_only',true) IS DISTINCT FROM 'YES' THEN
    RAISE EXCEPTION 'C11_DISPOSABLE_PG17_ONLY';
  END IF;
END $gate$;

BEGIN;
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;
CREATE SCHEMA grid_c11;
REVOKE ALL ON SCHEMA grid_c11 FROM PUBLIC;

CREATE FUNCTION grid_c11.verify_options_evidence_v1(
  p_canonical_json text, p_jsonb jsonb, p_expected_sha256 text,
  p_utf8_length integer, p_organisation_uuid uuid, p_schedule_uuid uuid,
  p_source_revision integer, p_source_grid_json_1_sha256 text,
  p_c4_validated_teaching_sha256 text
) RETURNS boolean
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $body$
BEGIN
  IF p_canonical_json IS NULL OR p_jsonb IS NULL OR p_expected_sha256 IS NULL
     OR p_utf8_length IS NULL OR p_organisation_uuid IS NULL OR p_schedule_uuid IS NULL
     OR p_source_revision IS NULL OR p_source_grid_json_1_sha256 IS NULL
     OR p_c4_validated_teaching_sha256 IS NULL THEN
    RAISE EXCEPTION 'C11_MISSING_BOUND_EVIDENCE' USING ERRCODE='22023';
  END IF;
  IF p_utf8_length NOT BETWEEN 1 AND 4000000 OR
     pg_catalog.octet_length(pg_catalog.convert_to(p_canonical_json,'UTF8')) <> p_utf8_length THEN
    RAISE EXCEPTION 'C11_CANONICAL_BYTE_LENGTH' USING ERRCODE='22023';
  END IF;
  IF p_expected_sha256 !~ '^[0-9a-f]{64}$' OR
     pg_catalog.encode(public.digest(pg_catalog.convert_to(p_canonical_json,'UTF8'),'sha256'),'hex')
       <> p_expected_sha256 THEN
    RAISE EXCEPTION 'C11_BYTE_HASH_MISMATCH' USING ERRCODE='22023';
  END IF;
  -- Important: JSONB equality checks decoded *content*, not canonicality.
  -- The trusted Python verifier must independently reject noncanonical JSON,
  -- duplicate object keys and invalid/unsupported option witness shapes.
  IF p_canonical_json::jsonb <> p_jsonb THEN
    RAISE EXCEPTION 'C11_JSONB_CONTENT_MISMATCH' USING ERRCODE='22023';
  END IF;
  IF p_jsonb->>'contract_version' IS DISTINCT FROM 'veni-grid.c11.options-evidence.v1'
     OR p_jsonb->>'serializer' IS DISTINCT FROM 'GRID-JSON-1'
     OR p_jsonb->>'schedule_kind' IS DISTINCT FROM 'ACADEMIC_OPTIONS'
     OR pg_catalog.jsonb_typeof(p_jsonb->'scope') IS DISTINCT FROM 'object'
     OR pg_catalog.jsonb_typeof(p_jsonb->'accepted_options') IS DISTINCT FROM 'object'
     OR (SELECT count(*) FROM pg_catalog.jsonb_object_keys(p_jsonb)) <> 6
     OR (SELECT count(*) FROM pg_catalog.jsonb_object_keys(p_jsonb->'scope')) <> 5
     OR p_jsonb->>'accepted_options_grid_json_1_sha256' !~ '^[0-9a-f]{64}$'
     OR p_source_grid_json_1_sha256 !~ '^[0-9a-f]{64}$'
     OR p_c4_validated_teaching_sha256 !~ '^[0-9a-f]{64}$'
     OR p_source_revision < 1 THEN
    RAISE EXCEPTION 'C11_ENVELOPE_VERSION_OR_TYPE' USING ERRCODE='22023';
  END IF;
  IF (p_jsonb->'scope'->>'organisation_uuid') IS DISTINCT FROM p_organisation_uuid::text
     OR (p_jsonb->'scope'->>'schedule_uuid') IS DISTINCT FROM p_schedule_uuid::text
     OR (p_jsonb->'scope'->>'source_revision') IS DISTINCT FROM p_source_revision::text
     OR (p_jsonb->'scope'->>'source_grid_json_1_sha256') IS DISTINCT FROM p_source_grid_json_1_sha256
     OR (p_jsonb->'scope'->>'c4_validated_teaching_sha256') IS DISTINCT FROM p_c4_validated_teaching_sha256 THEN
    RAISE EXCEPTION 'C11_WRONG_SCHOOL_SCHEDULE_OR_SOURCE' USING ERRCODE='22023';
  END IF;
  RETURN true;
END $body$;

REVOKE ALL ON FUNCTION grid_c11.verify_options_evidence_v1(
  text,jsonb,text,integer,uuid,uuid,integer,text,text) FROM PUBLIC;
COMMIT;
