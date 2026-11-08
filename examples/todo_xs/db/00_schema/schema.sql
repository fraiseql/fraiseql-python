-- ==============================================================================
-- TODO APP - XS (Extra Small) Example
-- ==============================================================================
-- Single file schema for prototypes and demos
-- Project size: <100 lines, 2-3 tables
-- Organization: Everything in one file (XS pattern)
-- ==============================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ==============================================================================
-- WRITE SIDE (Command): tb_* tables
-- ==============================================================================

-- Users table (write side)
CREATE TABLE tb_user (
    -- Trinity pattern identifiers
    pk_user INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id UUID DEFAULT gen_random_uuid() UNIQUE NOT NULL,
    identifier TEXT UNIQUE NOT NULL,

    -- User data
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Todos table (write side)
CREATE TABLE tb_todo (
    -- Trinity pattern identifiers
    pk_todo INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id UUID DEFAULT gen_random_uuid() UNIQUE NOT NULL,

    -- Todo data
    fk_user INT NOT NULL REFERENCES tb_user(pk_user) ON DELETE CASCADE,
    title TEXT NOT NULL,
    completed BOOLEAN DEFAULT false,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ==============================================================================
-- READ SIDE (Query): v_* views
-- ==============================================================================

-- User view (read side)
CREATE VIEW v_user AS
SELECT
    u.id,
    u.identifier,
    jsonb_build_object(
        'id', u.id::text,
        'identifier', u.identifier,
        'email', u.email,
        'name', u.name,
        'created_at', u.created_at
    ) AS data
FROM tb_user u;

-- Todo view with user data (read side)
CREATE VIEW v_todo AS
SELECT
    t.id,
    jsonb_build_object(
        'id', t.id::text,
        'title', t.title,
        'completed', t.completed,
        'created_at', t.created_at,
        'user', jsonb_build_object(
            'id', u.id::text,
            'name', u.name
        )
    ) AS data
FROM tb_todo t
JOIN tb_user u ON u.pk_user = t.fk_user;

-- ==============================================================================
-- INDEXES
-- ==============================================================================

CREATE INDEX idx_tb_user_id ON tb_user(id);
CREATE INDEX idx_tb_todo_id ON tb_todo(id);
CREATE INDEX idx_tb_todo_fk_user ON tb_todo(fk_user);
