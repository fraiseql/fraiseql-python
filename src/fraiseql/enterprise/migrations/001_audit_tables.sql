-- src/fraiseql/enterprise/migrations/001_audit_tables.sql

-- Enable pgcrypto extension for cryptographic functions
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Table to store audit signing keys (managed separately for security)
CREATE TABLE IF NOT EXISTS audit_signing_keys (
    id SERIAL PRIMARY KEY,
    key_value TEXT NOT NULL,  -- Encrypted or managed by external key vault
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS audit_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type VARCHAR(100) NOT NULL,
    event_data JSONB NOT NULL,
    user_id UUID,
    tenant_id UUID,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ip_address INET,
    previous_hash VARCHAR(64),
    event_hash VARCHAR(64) NOT NULL,
    signature VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Which hash an event's event_hash is (see generate_event_hash_v2 below). Version 1
-- hashed only event_data, so changing event_type, user_id, tenant_id, timestamp or
-- ip_address went unnoticed by verify_audit_chain(). Events written before 1.31.1
-- keep version 1 (the ADD COLUMN default) and still verify; the trigger writes
-- version 2 for every new event.
ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS hash_version SMALLINT NOT NULL DEFAULT 1;
ALTER TABLE audit_events ALTER COLUMN hash_version SET DEFAULT 2;

-- Prevent updates and deletes
DROP POLICY IF EXISTS audit_events_insert_only ON audit_events;
CREATE POLICY audit_events_insert_only ON audit_events
    FOR ALL
    USING (false)
    WITH CHECK (true);

-- Index for chain verification
CREATE INDEX IF NOT EXISTS idx_audit_events_hash ON audit_events(event_hash);
CREATE INDEX IF NOT EXISTS idx_audit_events_timestamp ON audit_events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_tenant ON audit_events(tenant_id, timestamp DESC);

-- Function to get current active signing key
CREATE OR REPLACE FUNCTION get_active_signing_key()
RETURNS TEXT AS $$
    SELECT key_value FROM audit_signing_keys
    WHERE active = TRUE
    ORDER BY created_at DESC
    LIMIT 1;
$$ LANGUAGE sql SECURITY DEFINER;

-- Version 1 event hash: covers event_data only. Kept to verify events written
-- before 1.31.1 (hash_version = 1); new events use generate_event_hash_v2.
CREATE OR REPLACE FUNCTION generate_event_hash(
    event_data JSONB,
    previous_hash TEXT DEFAULT NULL
)
RETURNS TEXT AS $$
DECLARE
    canonical_json TEXT;
    chain_data TEXT;
BEGIN
    -- Create canonical JSON representation
    canonical_json := jsonb_build_object(
        'event_type', event_data->>'event_type',
        'event_data', event_data - 'event_type'  -- Remove event_type from data
    )::TEXT;

    -- Create chain data: previous_hash:event_data
    chain_data := COALESCE(previous_hash || ':', 'GENESIS:') || canonical_json;

    -- Generate SHA-256 hash
    RETURN encode(digest(chain_data, 'sha256'), 'hex');
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Version 2 event hash: covers every column of the event (all but the hash, the
-- signature and previous_hash, which is the chain link itself). The timestamps are
-- written in UTC, so the hash doesn't depend on the session's TimeZone.
CREATE OR REPLACE FUNCTION generate_event_hash_v2(
    p_id UUID,
    p_event_type TEXT,
    p_event_data JSONB,
    p_user_id UUID,
    p_tenant_id UUID,
    p_timestamp TIMESTAMPTZ,
    p_ip_address INET,
    p_created_at TIMESTAMPTZ,
    p_previous_hash TEXT
)
RETURNS TEXT AS $$
    SELECT encode(digest(
        COALESCE(p_previous_hash || ':', 'GENESIS:') || jsonb_build_object(
            'hash_version', 2,
            'id', p_id::TEXT,
            'event_type', p_event_type,
            'event_data', p_event_data,
            'user_id', p_user_id::TEXT,
            'tenant_id', p_tenant_id::TEXT,
            'timestamp', to_char(p_timestamp AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
            'ip_address', p_ip_address::TEXT,
            'created_at', to_char(p_created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
        )::TEXT,
        'sha256'), 'hex');
$$ LANGUAGE sql STABLE;

-- The hash an event should have, by its hash_version (NULL for an unknown version).
CREATE OR REPLACE FUNCTION compute_event_hash(e audit_events, previous_hash TEXT)
RETURNS TEXT AS $$
    SELECT CASE e.hash_version
        WHEN 1 THEN generate_event_hash(e.event_data, previous_hash)
        WHEN 2 THEN generate_event_hash_v2(
            e.id, e.event_type, e.event_data, e.user_id, e.tenant_id,
            e.timestamp, e.ip_address, e.created_at, previous_hash)
    END;
$$ LANGUAGE sql STABLE;

-- Function to generate HMAC signature
CREATE OR REPLACE FUNCTION generate_event_signature(event_hash TEXT)
RETURNS TEXT AS $$
DECLARE
    signing_key TEXT;
BEGIN
    -- Get active signing key
    SELECT get_active_signing_key() INTO signing_key;
    IF signing_key IS NULL THEN
        RAISE EXCEPTION 'No active signing key available';
    END IF;

    -- Generate HMAC-SHA256 signature
    RETURN encode(hmac(event_hash, signing_key, 'sha256'), 'hex');
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to get latest event hash for chain linking (per-tenant)
CREATE OR REPLACE FUNCTION get_latest_event_hash(p_tenant_id UUID)
RETURNS TEXT AS $$
    SELECT event_hash FROM audit_events
    WHERE tenant_id = p_tenant_id OR (tenant_id IS NULL AND p_tenant_id IS NULL)
    ORDER BY timestamp DESC, id DESC
    LIMIT 1;
$$ LANGUAGE sql;

-- Function to populate crypto fields before insert
CREATE OR REPLACE FUNCTION populate_crypto_fields()
RETURNS TRIGGER AS $$
DECLARE
    prev_hash TEXT;
BEGIN
    -- Get previous hash for chain (per-tenant to support multi-tenancy)
    SELECT get_latest_event_hash(NEW.tenant_id) INTO prev_hash;

    -- Generate event hash (always the current version, whatever the INSERT says)
    NEW.hash_version := 2;
    NEW.event_hash := compute_event_hash(NEW, prev_hash);

    -- Generate signature
    NEW.signature := generate_event_signature(NEW.event_hash);

    -- Set previous hash for next event
    NEW.previous_hash := prev_hash;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Function to verify chain integrity.
-- The trigger chains each tenant's events on their own (events without a tenant
-- form one more chain), so this walks each tenant's events in time order and
-- recomputes each event_hash from the event before it in the same tenant. With a
-- start_timestamp, a tenant's first event in the range is checked against the
-- tenant's latest event before it. Each event is checked with the hash of its
-- hash_version: events written before 1.31.1 verify as version 1, which doesn't cover
-- event_type, user_id, tenant_id, timestamp or ip_address. Signatures are not checked.
-- Earlier versions returned no tenant_id or hash_version column; the return type
-- changed, hence the DROP.
DROP FUNCTION IF EXISTS verify_audit_chain(TIMESTAMPTZ, TIMESTAMPTZ);
CREATE FUNCTION verify_audit_chain(
    start_timestamp TIMESTAMPTZ DEFAULT NULL,
    end_timestamp TIMESTAMPTZ DEFAULT NULL
)
RETURNS TABLE(
    event_id UUID,
    event_timestamp TIMESTAMPTZ,
    chain_valid BOOLEAN,
    expected_hash TEXT,
    actual_hash TEXT,
    tenant_id UUID,
    hash_version SMALLINT
) AS $$
DECLARE
    rec RECORD;
    prev_hash TEXT := NULL;
    expected TEXT;
    first_row BOOLEAN := TRUE;
    current_tenant UUID := NULL;
BEGIN
    -- Each tenant's events in chronological order (the order the trigger links them in)
    FOR rec IN
        SELECT e.id, e.timestamp AS ts, e.tenant_id AS tid, e.event_hash,
               e.hash_version AS hv, e AS ev
        FROM audit_events e
        WHERE (start_timestamp IS NULL OR e.timestamp >= start_timestamp)
          AND (end_timestamp IS NULL OR e.timestamp <= end_timestamp)
        ORDER BY e.tenant_id NULLS LAST, e.timestamp ASC, e.id ASC
    LOOP
        IF first_row OR rec.tid IS DISTINCT FROM current_tenant THEN
            -- A new tenant chain: start from the tenant's event before this one, if any
            first_row := FALSE;
            current_tenant := rec.tid;
            SELECT p.event_hash INTO prev_hash
            FROM audit_events p
            WHERE p.tenant_id IS NOT DISTINCT FROM rec.tid
              AND (p.timestamp, p.id) < (rec.ts, rec.id)
            ORDER BY p.timestamp DESC, p.id DESC
            LIMIT 1;
        END IF;

        -- Calculate expected hash
        expected := compute_event_hash(rec.ev, prev_hash);

        -- Return verification result
        event_id := rec.id;
        event_timestamp := rec.ts;
        chain_valid := COALESCE(expected = rec.event_hash, FALSE);
        expected_hash := expected;
        actual_hash := rec.event_hash;
        tenant_id := rec.tid;
        hash_version := rec.hv;

        RETURN NEXT;

        -- Update previous hash for next iteration
        prev_hash := rec.event_hash;
    END LOOP;

    RETURN;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-populate cryptographic fields
DROP TRIGGER IF EXISTS populate_crypto_trigger ON audit_events;
CREATE TRIGGER populate_crypto_trigger
    BEFORE INSERT ON audit_events
    FOR EACH ROW EXECUTE FUNCTION populate_crypto_fields();

-- audit_events is a plain table. Earlier versions of this file installed a
-- create_audit_partition_trigger that tried to create a monthly partition from a
-- BEFORE INSERT trigger: the table isn't partitioned, and a row trigger can't add
-- a partition to the table it's inserting into, so every insert failed. Re-running
-- this file removes it. To partition the table, create it partitioned yourself
-- (PARTITION BY RANGE (timestamp), with timestamp in the primary key) and create
-- the partitions ahead of time (pg_partman, or a scheduled job).
DROP TRIGGER IF EXISTS create_audit_partition_trigger ON audit_events;
DROP FUNCTION IF EXISTS create_audit_partition();

-- ============================================================================
-- BRIDGE: Connect existing tb_audit_log to cryptographic audit_events
-- ============================================================================

-- Function to bridge tenant.tb_audit_log entries to cryptographic audit_events
-- This allows existing log_and_return_mutation() calls to automatically
-- benefit from cryptographic chain integrity
CREATE OR REPLACE FUNCTION bridge_audit_to_chain()
RETURNS TRIGGER AS $$
BEGIN
    -- Insert into cryptographic audit_events table
    -- PostgreSQL triggers will handle: previous_hash, event_hash, signature
    INSERT INTO audit_events (
        id,
        event_type,
        event_data,
        user_id,
        tenant_id,
        timestamp,
        ip_address
    ) VALUES (
        NEW.pk_audit_log,  -- Use same ID for correlation
        format('%s.%s', NEW.operation_type, COALESCE(NEW.operation_subtype, 'default')),
        jsonb_build_object(
            'entity_type', NEW.entity_type,
            'entity_id', NEW.entity_id,
            'operation_type', NEW.operation_type,
            'operation_subtype', NEW.operation_subtype,
            'changed_fields', NEW.changed_fields,
            'old_data', NEW.old_data,
            'new_data', NEW.new_data,
            'metadata', NEW.metadata,
            'correlation_id', NEW.correlation_id
        ),
        NEW.user_id,
        NEW.pk_organization,  -- Use organization as tenant
        NEW.created_at,
        NULL  -- IP address not in tb_audit_log (can be added later)
    );

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Note: Trigger is NOT created here automatically
-- Each project should decide whether to enable the bridge by running:
--
-- CREATE TRIGGER bridge_to_cryptographic_audit
--     AFTER INSERT ON tenant.tb_audit_log
--     FOR EACH ROW
--     EXECUTE FUNCTION bridge_audit_to_chain();
--
-- This opt-in approach allows projects to:
-- 1. Use only tb_audit_log (existing behavior)
-- 2. Use only audit_events (cryptographic chain only)
-- 3. Use both (bridge enabled for compliance requirements)
