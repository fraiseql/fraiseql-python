-- Native authentication schema
--
-- The tables fraiseql.auth.native reads and writes: users, their sessions, the
-- refresh tokens already used, and password reset requests.
--
-- apply_native_auth_schema(pool, schema) runs this file with search_path set to
-- `schema`, so the names below are unqualified. Every statement is idempotent: the
-- file can be applied again (at each startup, for example).
--
-- Requires PostgreSQL 13+ (gen_random_uuid() is built in).

CREATE TABLE IF NOT EXISTS tb_user (
    pk_user UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    name TEXT,
    roles TEXT[] NOT NULL DEFAULT '{}',
    permissions TEXT[] NOT NULL DEFAULT '{}',
    metadata JSONB NOT NULL DEFAULT '{}',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- One row per login: the refresh tokens of a login share its token_family.
CREATE TABLE IF NOT EXISTS tb_session (
    pk_session UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fk_user UUID NOT NULL REFERENCES tb_user (pk_user) ON DELETE CASCADE,
    token_family UUID NOT NULL,
    user_agent TEXT,
    ip_address TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_active TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tb_session_fk_user ON tb_session (fk_user);
CREATE INDEX IF NOT EXISTS idx_tb_session_token_family ON tb_session (token_family);

-- Refresh tokens already exchanged: presenting one again is refused.
CREATE TABLE IF NOT EXISTS tb_used_refresh_token (
    token_jti TEXT PRIMARY KEY,
    family_id UUID NOT NULL,
    used_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tb_used_refresh_token_family
    ON tb_used_refresh_token (family_id);

-- Password reset requests. Only the SHA-256 of the reset token is stored.
-- POST /reset-password reads `pr.*` followed by the user id: keep these six columns,
-- in this order.
CREATE TABLE IF NOT EXISTS tb_password_reset (
    pk_password_reset UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fk_user UUID NOT NULL REFERENCES tb_user (pk_user) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tb_password_reset_fk_user ON tb_password_reset (fk_user);
