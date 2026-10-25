-- src/fraiseql/enterprise/migrations/002_unified_audit.sql
--
-- UNIFIED AUDIT TABLE: Combines CDC (Debezium-style) + Cryptographic Chain
-- Philosophy: "In PostgreSQL Everything" - One source of truth for all audit data
--
-- This replaces the need for:
-- - tenant.tb_audit_log (CDC data)
-- - audit_events (crypto chain)
-- - bridge_audit_to_chain() trigger
--
-- Features:
-- ✅ Cryptographic chain integrity (hash, signature, previous_hash)
-- ✅ CDC-style change tracking (old_data, new_data, changed_fields)
-- ✅ Multi-tenant isolation (tenant_id with per-tenant chains)
-- ✅ Business metadata (operation subtypes, correlation, business_actions)
-- ✅ Tamper-proof (append-only, RLS policies)

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================================
-- SIGNING KEY MANAGEMENT
-- ============================================================================

CREATE TABLE IF NOT EXISTS audit_signing_keys (
    id SERIAL PRIMARY KEY,
    key_value TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    active BOOLEAN NOT NULL DEFAULT TRUE
);

-- ============================================================================
-- UNIFIED AUDIT TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS audit_events (
    -- Primary identification
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Multi-tenancy
    tenant_id UUID NOT NULL,
    user_id UUID,

    -- Entity tracking (CDC)
    entity_type TEXT NOT NULL,
    entity_id UUID,

    -- Operation classification
    operation_type TEXT NOT NULL, -- INSERT, UPDATE, DELETE, NOOP
    operation_subtype TEXT,       -- new, updated, noop:duplicate, etc.

    -- Change tracking (Debezium-style CDC)
    changed_fields TEXT[],
    old_data JSONB,
    new_data JSONB,

    -- Business metadata
    metadata JSONB,               -- business_actions, validation results, etc.

    -- Context
    ip_address INET,
    correlation_id UUID DEFAULT gen_random_uuid(),

    -- Timestamps
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Cryptographic chain integrity
    previous_hash VARCHAR(64),    -- Links to previous event in tenant chain
    event_hash VARCHAR(64) NOT NULL,
    signature VARCHAR(128) NOT NULL
);

-- ============================================================================
-- SECURITY: Row-Level Security & Policies
-- ============================================================================

-- Enable RLS
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;

-- Append-only policy: Allow INSERT, prevent UPDATE/DELETE
DROP POLICY IF EXISTS audit_events_insert_only ON audit_events;
CREATE POLICY audit_events_insert_only ON audit_events
    FOR ALL
    USING (false)          -- No SELECT/UPDATE/DELETE allowed via this policy
    WITH CHECK (true);     -- INSERT allowed

-- ============================================================================
-- INDEXES FOR PERFORMANCE
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_audit_events_tenant_time
    ON audit_events(tenant_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_audit_events_entity
    ON audit_events(entity_type, entity_id);

CREATE INDEX IF NOT EXISTS idx_audit_events_hash
    ON audit_events(event_hash);

CREATE INDEX IF NOT EXISTS idx_audit_events_correlation
    ON audit_events(correlation_id);

CREATE INDEX IF NOT EXISTS idx_audit_events_operation
    ON audit_events(operation_type, operation_subtype);

-- GIN index for metadata queries
CREATE INDEX IF NOT EXISTS idx_audit_events_metadata
    ON audit_events USING GIN (metadata);

-- ============================================================================
-- CRYPTOGRAPHIC FUNCTIONS
-- ============================================================================

-- Get active signing key
CREATE OR REPLACE FUNCTION get_active_signing_key()
RETURNS TEXT AS $$
    SELECT key_value FROM audit_signing_keys
    WHERE active = TRUE
    ORDER BY created_at DESC
    LIMIT 1;
$$ LANGUAGE sql SECURITY DEFINER;

-- Generate event hash with chain linking
CREATE OR REPLACE FUNCTION generate_event_hash(
    p_tenant_id UUID,
    p_entity_type TEXT,
    p_entity_id UUID,
    p_operation_type TEXT,
    p_operation_subtype TEXT,
    p_changed_fields TEXT[],
    p_old_data JSONB,
    p_new_data JSONB,
    p_metadata JSONB,
    p_timestamp TIMESTAMPTZ,
    p_previous_hash TEXT
)
RETURNS TEXT AS $$
DECLARE
    canonical_json TEXT;
    chain_data TEXT;
BEGIN
    -- Create canonical JSON representation (deterministic ordering)
    canonical_json := jsonb_build_object(
        'tenant_id', p_tenant_id::TEXT,
        'entity_type', p_entity_type,
        'entity_id', p_entity_id::TEXT,
        'operation_type', p_operation_type,
        'operation_subtype', p_operation_subtype,
        'changed_fields', to_jsonb(p_changed_fields),
        'old_data', p_old_data,
        'new_data', p_new_data,
        'metadata', p_metadata,
        'timestamp', p_timestamp::TEXT
    )::TEXT;

    -- Chain data: previous_hash:event_data
    chain_data := COALESCE(p_previous_hash || ':', 'GENESIS:') || canonical_json;

    -- Generate SHA-256 hash
    RETURN encode(digest(chain_data, 'sha256'), 'hex');
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Generate HMAC signature
CREATE OR REPLACE FUNCTION generate_event_signature(event_hash TEXT)
RETURNS TEXT AS $$
DECLARE
    signing_key TEXT;
BEGIN
    SELECT get_active_signing_key() INTO signing_key;
    IF signing_key IS NULL THEN
        RAISE EXCEPTION 'No active signing key available';
    END IF;

    RETURN encode(hmac(event_hash, signing_key, 'sha256'), 'hex');
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Get latest event hash for chain linking (per-tenant)
CREATE OR REPLACE FUNCTION get_latest_event_hash(p_tenant_id UUID)
RETURNS TEXT AS $$
    SELECT event_hash FROM audit_events
    WHERE tenant_id = p_tenant_id
    ORDER BY timestamp DESC, id DESC
    LIMIT 1;
$$ LANGUAGE sql;

-- ============================================================================
-- TRIGGER: Auto-populate cryptographic fields
-- ============================================================================

CREATE OR REPLACE FUNCTION populate_crypto_fields()
RETURNS TRIGGER AS $$
DECLARE
    prev_hash TEXT;
BEGIN
    -- Get previous hash for chain (per-tenant)
    SELECT get_latest_event_hash(NEW.tenant_id) INTO prev_hash;

    -- Generate event hash
    NEW.event_hash := generate_event_hash(
        NEW.tenant_id,
        NEW.entity_type,
        NEW.entity_id,
        NEW.operation_type,
        NEW.operation_subtype,
        NEW.changed_fields,
        NEW.old_data,
        NEW.new_data,
        NEW.metadata,
        NEW.timestamp,
        prev_hash
    );

    -- Generate signature
    NEW.signature := generate_event_signature(NEW.event_hash);

    -- Set previous hash for chain verification
    NEW.previous_hash := prev_hash;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS populate_crypto_trigger ON audit_events;
CREATE TRIGGER populate_crypto_trigger
    BEFORE INSERT ON audit_events
    FOR EACH ROW EXECUTE FUNCTION populate_crypto_fields();

-- ============================================================================
-- HELPER: Updated log_and_return_mutation() for unified table
-- ============================================================================

-- Note: This is a reference implementation. Projects should adapt based on their needs.
--
-- Example usage in your mutation functions:
--
-- RETURN log_and_return_mutation(
--     input_pk_organization,  -- tenant_id
--     input_created_by,       -- user_id
--     'post',                 -- entity_type
--     v_post_id,              -- entity_id
--     'INSERT',               -- operation_type
--     'new',                  -- operation_subtype
--     ARRAY['title', 'content'], -- changed_fields
--     'Post created',         -- message
--     NULL,                   -- old_data
--     (SELECT data FROM v_post WHERE id = v_post_id), -- new_data
--     jsonb_build_object(
--         'business_actions', ARRAY['slug_generated', 'stats_initialized'],
--         'generated_slug', v_slug
--     )                       -- metadata
-- );

CREATE OR REPLACE FUNCTION log_and_return_mutation(
    p_tenant_id UUID,
    p_user_id UUID,
    p_entity_type TEXT,
    p_entity_id UUID,
    p_operation_type TEXT,
    p_operation_subtype TEXT,
    p_changed_fields TEXT[],
    p_message TEXT,
    p_old_data JSONB,
    p_new_data JSONB,
    p_metadata JSONB
) RETURNS TABLE (
    success BOOLEAN,
    operation_type TEXT,
    entity_type TEXT,
    entity_id UUID,
    message TEXT,
    error_code TEXT,
    changed_fields TEXT[],
    old_data JSONB,
    new_data JSONB,
    metadata JSONB
) AS $$
BEGIN
    -- Log to unified audit table
    -- Crypto fields (event_hash, signature, previous_hash) are auto-populated by trigger
    INSERT INTO audit_events (
        tenant_id, user_id, entity_type, entity_id,
        operation_type, operation_subtype, changed_fields,
        old_data, new_data, metadata
    ) VALUES (
        p_tenant_id, p_user_id, p_entity_type, p_entity_id,
        p_operation_type, p_operation_subtype, p_changed_fields,
        p_old_data, p_new_data, p_metadata
    );

    -- Return standardized result
    RETURN QUERY SELECT
        (p_operation_type IN ('INSERT', 'UPDATE', 'DELETE'))::BOOLEAN,
        p_operation_type,
        p_entity_type,
        p_entity_id,
        p_message,
        CASE WHEN p_operation_type = 'NOOP' THEN p_operation_subtype ELSE NULL END,
        p_changed_fields,
        p_old_data,
        p_new_data,
        p_metadata;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- CHAIN VERIFICATION
-- ============================================================================

-- The trigger chains each tenant's events on their own: walk each tenant's events in
-- time order and recompute each event_hash from the event before it in the same
-- tenant. With p_start_timestamp, a tenant's first event in the range is checked
-- against the tenant's latest event before it. Signatures are not checked.
CREATE OR REPLACE FUNCTION verify_audit_chain(
    p_tenant_id UUID DEFAULT NULL,
    p_start_timestamp TIMESTAMPTZ DEFAULT NULL,
    p_end_timestamp TIMESTAMPTZ DEFAULT NULL
)
RETURNS TABLE(
    event_id UUID,
    event_timestamp TIMESTAMPTZ,
    chain_valid BOOLEAN,
    expected_hash TEXT,
    actual_hash TEXT
) AS $$
DECLARE
    rec RECORD;
    prev_hash TEXT := NULL;
    expected TEXT;
    first_row BOOLEAN := TRUE;
    current_tenant UUID := NULL;
BEGIN
    FOR rec IN
        SELECT
            id, timestamp, tenant_id, entity_type, entity_id,
            operation_type, operation_subtype, changed_fields,
            old_data, new_data, metadata, event_hash, previous_hash
        FROM audit_events
        WHERE (p_tenant_id IS NULL OR tenant_id = p_tenant_id)
          AND (p_start_timestamp IS NULL OR timestamp >= p_start_timestamp)
          AND (p_end_timestamp IS NULL OR timestamp <= p_end_timestamp)
        ORDER BY tenant_id, timestamp ASC, id ASC
    LOOP
        IF first_row OR rec.tenant_id IS DISTINCT FROM current_tenant THEN
            -- A new tenant chain: start from the tenant's event before this one, if any
            first_row := FALSE;
            current_tenant := rec.tenant_id;
            SELECT p.event_hash INTO prev_hash
            FROM audit_events p
            WHERE p.tenant_id = rec.tenant_id
              AND (p.timestamp, p.id) < (rec.timestamp, rec.id)
            ORDER BY p.timestamp DESC, p.id DESC
            LIMIT 1;
        END IF;

        -- Calculate expected hash
        expected := generate_event_hash(
            rec.tenant_id, rec.entity_type, rec.entity_id,
            rec.operation_type, rec.operation_subtype, rec.changed_fields,
            rec.old_data, rec.new_data, rec.metadata,
            rec.timestamp, prev_hash
        );

        -- Return verification result
        event_id := rec.id;
        event_timestamp := rec.timestamp;
        chain_valid := (expected = rec.event_hash);
        expected_hash := expected;
        actual_hash := rec.event_hash;

        RETURN NEXT;

        -- Update previous hash for next iteration
        prev_hash := rec.event_hash;
    END LOOP;

    RETURN;
END;
$$ LANGUAGE plpgsql;
