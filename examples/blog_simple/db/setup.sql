-- FraiseQL Blog Simple - Database Schema with Trinity Pattern
-- Complete PostgreSQL setup for blog application following FraiseQL v1 patterns

-- Drop existing objects if they exist (for clean setup)
DROP VIEW IF EXISTS v_post, v_comment, v_tag, v_user;
DROP TABLE IF EXISTS tb_post_tag;
DROP TABLE IF EXISTS tb_comment;
DROP TABLE IF EXISTS tb_post;
DROP TABLE IF EXISTS tb_tag;
DROP TABLE IF EXISTS tb_user;

-- ==============================================================================
-- BASE TABLES (tb_*): Normalized, write-optimized, source of truth
-- ==============================================================================

-- Users table - Trinity Pattern
CREATE TABLE tb_user (
    -- Trinity Identifiers
    pk_user INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,  -- Internal (fast INT joins)
    id UUID DEFAULT gen_random_uuid() UNIQUE NOT NULL,     -- Public API (secure UUID)
    identifier TEXT UNIQUE NOT NULL,                       -- Human-readable (username/slug)

    -- User data
    email TEXT NOT NULL UNIQUE CHECK (email ~ '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'),
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'author', 'user')),
    profile_data JSONB DEFAULT '{}'::jsonb,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Constraints
    CONSTRAINT chk_username_length CHECK (length(identifier) >= 3)
);

-- Tags table - Trinity Pattern
CREATE TABLE tb_tag (
    -- Trinity Identifiers
    pk_tag INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,   -- Internal (fast INT joins)
    id UUID DEFAULT gen_random_uuid() UNIQUE NOT NULL,     -- Public API (secure UUID)
    identifier TEXT UNIQUE NOT NULL,                       -- Human-readable (slug)

    -- Tag data
    name TEXT NOT NULL UNIQUE CHECK (length(name) >= 1),
    color TEXT DEFAULT '#6366f1' CHECK (color ~ '^#[0-9A-Fa-f]{6}$'),
    description TEXT,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Posts table - Trinity Pattern with INT foreign keys
CREATE TABLE tb_post (
    -- Trinity Identifiers
    pk_post INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,  -- Internal (fast INT joins)
    id UUID DEFAULT gen_random_uuid() UNIQUE NOT NULL,     -- Public API (secure UUID)
    identifier TEXT UNIQUE NOT NULL,                       -- Human-readable (slug)

    -- Post data
    title TEXT NOT NULL CHECK (length(title) >= 1),
    content TEXT NOT NULL CHECK (length(content) >= 1),
    excerpt TEXT,
    fk_author INT NOT NULL REFERENCES tb_user(pk_user) ON DELETE CASCADE,  -- Fast INT FK!
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'archived')),
    published_at TIMESTAMPTZ,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Comments table - Trinity Pattern with INT foreign keys
CREATE TABLE tb_comment (
    -- Trinity Identifiers
    pk_comment INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,  -- Internal (fast INT joins)
    id UUID DEFAULT gen_random_uuid() UNIQUE NOT NULL,        -- Public API (secure UUID)
    identifier TEXT UNIQUE,                                   -- Optional for comments

    -- Comment data
    fk_post INT NOT NULL REFERENCES tb_post(pk_post) ON DELETE CASCADE,       -- Fast INT FK!
    fk_author INT NOT NULL REFERENCES tb_user(pk_user) ON DELETE CASCADE,     -- Fast INT FK!
    fk_parent INT REFERENCES tb_comment(pk_comment) ON DELETE CASCADE,        -- Fast INT FK!
    content TEXT NOT NULL CHECK (length(content) >= 1),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Many-to-many relationship between posts and tags (using INT FKs)
CREATE TABLE tb_post_tag (
    fk_post INT NOT NULL REFERENCES tb_post(pk_post) ON DELETE CASCADE,
    fk_tag INT NOT NULL REFERENCES tb_tag(pk_tag) ON DELETE CASCADE,
    PRIMARY KEY (fk_post, fk_tag)
);

-- ==============================================================================
-- INDEXES: Performance optimization using internal pk_* columns
-- ==============================================================================

-- User indexes
CREATE INDEX idx_tb_user_email ON tb_user(email);
CREATE INDEX idx_tb_user_identifier ON tb_user(identifier);
CREATE INDEX idx_tb_user_role ON tb_user(role);
CREATE INDEX idx_tb_user_id ON tb_user(id);  -- For UUID lookups from GraphQL

-- Tag indexes
CREATE INDEX idx_tb_tag_identifier ON tb_tag(identifier);
CREATE INDEX idx_tb_tag_name ON tb_tag(name);
CREATE INDEX idx_tb_tag_id ON tb_tag(id);  -- For UUID lookups from GraphQL

-- Post indexes (using INT foreign keys for performance)
CREATE INDEX idx_tb_post_fk_author ON tb_post(fk_author);
CREATE INDEX idx_tb_post_status ON tb_post(status);
CREATE INDEX idx_tb_post_published_at ON tb_post(published_at) WHERE published_at IS NOT NULL;
CREATE INDEX idx_tb_post_identifier ON tb_post(identifier);
CREATE INDEX idx_tb_post_id ON tb_post(id);  -- For UUID lookups from GraphQL
CREATE INDEX idx_tb_post_title_search ON tb_post USING GIN (to_tsvector('english', title));
CREATE INDEX idx_tb_post_content_search ON tb_post USING GIN (to_tsvector('english', content));

-- Comment indexes (using INT foreign keys for performance)
CREATE INDEX idx_tb_comment_fk_post ON tb_comment(fk_post);
CREATE INDEX idx_tb_comment_fk_author ON tb_comment(fk_author);
CREATE INDEX idx_tb_comment_fk_parent ON tb_comment(fk_parent) WHERE fk_parent IS NOT NULL;
CREATE INDEX idx_tb_comment_status ON tb_comment(status);
CREATE INDEX idx_tb_comment_id ON tb_comment(id);  -- For UUID lookups from GraphQL

-- Post tags indexes
CREATE INDEX idx_tb_post_tag_fk_tag ON tb_post_tag(fk_tag);

-- ==============================================================================
-- TRIGGERS: Automated updates
-- ==============================================================================

-- Trigger for updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_tb_user_updated_at
    BEFORE UPDATE ON tb_user
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_tb_post_updated_at
    BEFORE UPDATE ON tb_post
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_tb_comment_updated_at
    BEFORE UPDATE ON tb_comment
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Trigger to set published_at when status changes to published
CREATE OR REPLACE FUNCTION set_published_at()
RETURNS TRIGGER AS $$
BEGIN
    -- Set published_at when status changes to published
    IF NEW.status = 'published' AND (OLD.status != 'published' OR NEW.published_at IS NULL) THEN
        NEW.published_at = NOW();
    END IF;

    -- Clear published_at when status changes away from published
    IF NEW.status != 'published' AND OLD.status = 'published' THEN
        NEW.published_at = NULL;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tb_post_set_published_at
    BEFORE UPDATE ON tb_post
    FOR EACH ROW EXECUTE FUNCTION set_published_at();

-- ==============================================================================
-- HELPER FUNCTIONS: Slug generation and utilities
-- ==============================================================================

-- Function to generate slug from title
CREATE OR REPLACE FUNCTION generate_slug(input_text TEXT)
RETURNS TEXT AS $$
BEGIN
    RETURN lower(regexp_replace(
        regexp_replace(input_text, '[^a-zA-Z0-9\s]', '', 'g'),
        '\s+', '-', 'g'
    ));
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-generate slug from title for posts
CREATE OR REPLACE FUNCTION auto_generate_post_slug()
RETURNS TRIGGER AS $$
BEGIN
    -- Generate identifier (slug) from title if not provided
    IF NEW.identifier IS NULL OR NEW.identifier = '' THEN
        NEW.identifier = generate_slug(NEW.title);

        -- Ensure uniqueness by appending part of UUID
        WHILE EXISTS (SELECT 1 FROM tb_post WHERE identifier = NEW.identifier AND pk_post != COALESCE(NEW.pk_post, -1)) LOOP
            NEW.identifier = NEW.identifier || '-' || substr(NEW.id::text, 1, 8);
        END LOOP;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tb_post_auto_generate_slug
    BEFORE INSERT OR UPDATE ON tb_post
    FOR EACH ROW EXECUTE FUNCTION auto_generate_post_slug();

-- Trigger to auto-generate slug from name for tags
CREATE OR REPLACE FUNCTION auto_generate_tag_slug()
RETURNS TRIGGER AS $$
BEGIN
    -- Generate identifier (slug) from name if not provided
    IF NEW.identifier IS NULL OR NEW.identifier = '' THEN
        NEW.identifier = generate_slug(NEW.name);

        -- Ensure uniqueness by appending part of UUID
        WHILE EXISTS (SELECT 1 FROM tb_tag WHERE identifier = NEW.identifier AND pk_tag != COALESCE(NEW.pk_tag, -1)) LOOP
            NEW.identifier = NEW.identifier || '-' || substr(NEW.id::text, 1, 8);
        END LOOP;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tb_tag_auto_generate_slug
    BEFORE INSERT OR UPDATE ON tb_tag
    FOR EACH ROW EXECUTE FUNCTION auto_generate_tag_slug();

-- ==============================================================================
-- VIEWS (v_*): what the GraphQL types read
-- ==============================================================================
--
-- Each view has an id column (and the columns the queries filter on) plus a
-- data JSONB column holding the GraphQL object. Related objects are embedded:
-- a post's data holds its author, tags and approved comments, so one query
-- returns them without a resolver per field. pk_*/fk_* never leave the database.

CREATE VIEW v_user AS
SELECT
    u.pk_user,
    u.id,
    u.identifier,
    jsonb_build_object(
        'id', u.id,
        'identifier', u.identifier,
        'username', u.identifier,
        'email', u.email,
        'role', u.role,
        'profile_data', u.profile_data,
        'full_name', nullif(trim(concat_ws(' ',
            u.profile_data->>'first_name', u.profile_data->>'last_name')), ''),
        'created_at', u.created_at,
        'updated_at', u.updated_at
    ) AS data
FROM tb_user u;

CREATE VIEW v_tag AS
SELECT
    t.pk_tag,
    t.id,
    t.identifier,
    jsonb_build_object(
        'id', t.id,
        'identifier', t.identifier,
        'name', t.name,
        'slug', t.identifier,
        'color', t.color,
        'description', t.description
    ) AS data
FROM tb_tag t;

CREATE VIEW v_comment AS
SELECT
    c.pk_comment,
    c.id,
    c.fk_post,
    jsonb_build_object(
        'id', c.id,
        'content', c.content,
        'status', c.status,
        'created_at', c.created_at,
        'updated_at', c.updated_at,
        'post_id', p.id,
        'parent_id', parent.id,
        'author', u.data
    ) AS data
FROM tb_comment c
JOIN tb_post p ON p.pk_post = c.fk_post
JOIN v_user u ON u.pk_user = c.fk_author
LEFT JOIN tb_comment parent ON parent.pk_comment = c.fk_parent;

CREATE VIEW v_post AS
SELECT
    p.pk_post,
    p.id,
    p.identifier,
    a.id AS author_id,
    jsonb_build_object(
        'id', p.id,
        'identifier', p.identifier,
        'slug', p.identifier,
        'title', p.title,
        'content', p.content,
        'excerpt', p.excerpt,
        'status', p.status,
        'published_at', p.published_at,
        'created_at', p.created_at,
        'updated_at', p.updated_at,
        'author', a.data,
        'tags', coalesce((
            SELECT jsonb_agg(t.data ORDER BY t.data->>'name')
            FROM tb_post_tag pt
            JOIN v_tag t ON t.pk_tag = pt.fk_tag
            WHERE pt.fk_post = p.pk_post
        ), '[]'::jsonb),
        'comments', coalesce((
            SELECT jsonb_agg(c.data ORDER BY c.data->>'created_at')
            FROM v_comment c
            WHERE c.fk_post = p.pk_post AND c.data->>'status' = 'approved'
        ), '[]'::jsonb)
    ) AS data
FROM tb_post p
JOIN v_user a ON a.pk_user = p.fk_author;

-- ==============================================================================
-- MUTATIONS: one function per class mutation in models.py
-- ==============================================================================
--
-- fraiseql calls the function named after the mutation (CreatePost calls
-- create_post) with the context params first (here the caller's user id) and
-- the GraphQL input as one jsonb. The function returns a mutation_response:
-- a status such as 'created' or 'updated' selects the success type, and a
-- prefix such as 'validation:', 'forbidden:', 'not_found:' or 'conflict:' the
-- error type. The entity is the object the success type's field returns.

DO $$
BEGIN
    CREATE TYPE mutation_response AS (
        status          text,
        message         text,
        entity_id       text,
        entity_type     text,
        entity          jsonb,
        updated_fields  text[],
        cascade         jsonb,
        metadata        jsonb
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END
$$;

-- A mutation_response without an entity, for errors
CREATE OR REPLACE FUNCTION blog_error(p_status TEXT, p_message TEXT)
RETURNS mutation_response AS $$
    SELECT ROW(p_status, p_message, NULL, NULL, NULL, NULL, NULL, NULL)::mutation_response;
$$ LANGUAGE sql IMMUTABLE;

-- Attach tags (by public id) to a post
CREATE OR REPLACE FUNCTION set_post_tags(p_pk_post INT, p_tag_ids JSONB)
RETURNS VOID AS $$
BEGIN
    DELETE FROM tb_post_tag WHERE fk_post = p_pk_post;
    INSERT INTO tb_post_tag (fk_post, fk_tag)
    SELECT p_pk_post, t.pk_tag
    FROM tb_tag t
    WHERE t.id IN (SELECT jsonb_array_elements_text(p_tag_ids)::uuid);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION create_post(p_user_id UUID, input JSONB)
RETURNS mutation_response AS $$
DECLARE
    v_pk_author INT;
    v_pk_post INT;
    v_id UUID;
BEGIN
    SELECT pk_user INTO v_pk_author FROM tb_user WHERE id = p_user_id;
    IF v_pk_author IS NULL THEN
        RETURN blog_error('unauthorized:unknown_user', 'Unknown user');
    END IF;

    IF coalesce(trim(input->>'title'), '') = '' THEN
        RETURN blog_error('validation:title', 'Title is required');
    END IF;
    IF coalesce(trim(input->>'content'), '') = '' THEN
        RETURN blog_error('validation:content', 'Content is required');
    END IF;

    INSERT INTO tb_post (identifier, title, content, excerpt, fk_author)
    VALUES ('', input->>'title', input->>'content', input->>'excerpt', v_pk_author)
    RETURNING pk_post, id INTO v_pk_post, v_id;

    IF input ? 'tag_ids' THEN
        PERFORM set_post_tags(v_pk_post, input->'tag_ids');
    END IF;

    RETURN ROW(
        'created', 'Post created', v_id::text, 'Post',
        (SELECT data FROM v_post WHERE id = v_id), NULL, NULL, NULL
    )::mutation_response;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION update_post(p_user_id UUID, input JSONB)
RETURNS mutation_response AS $$
DECLARE
    v_id UUID := (input->>'id')::uuid;
    v_pk_post INT;
    v_author UUID;
BEGIN
    SELECT p.pk_post, u.id INTO v_pk_post, v_author
    FROM tb_post p JOIN tb_user u ON u.pk_user = p.fk_author
    WHERE p.id = v_id;

    IF v_pk_post IS NULL THEN
        RETURN blog_error('not_found:post', 'Post not found');
    END IF;
    IF v_author <> p_user_id THEN
        RETURN blog_error('forbidden:not_author', 'Only the author can edit this post');
    END IF;

    UPDATE tb_post
    SET title = coalesce(input->>'title', title),
        content = coalesce(input->>'content', content),
        excerpt = coalesce(input->>'excerpt', excerpt),
        status = coalesce(input->>'status', status)
    WHERE pk_post = v_pk_post;

    IF jsonb_typeof(input->'tag_ids') = 'array' THEN
        PERFORM set_post_tags(v_pk_post, input->'tag_ids');
    END IF;

    RETURN ROW(
        'updated', 'Post updated', v_id::text, 'Post',
        (SELECT data FROM v_post WHERE id = v_id),
        ARRAY(SELECT jsonb_object_keys(jsonb_strip_nulls(input - 'id'))), NULL, NULL
    )::mutation_response;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION create_comment(p_user_id UUID, input JSONB)
RETURNS mutation_response AS $$
DECLARE
    v_pk_author INT;
    v_pk_post INT;
    v_pk_parent INT;
    v_id UUID;
BEGIN
    SELECT pk_user INTO v_pk_author FROM tb_user WHERE id = p_user_id;
    IF v_pk_author IS NULL THEN
        RETURN blog_error('unauthorized:unknown_user', 'Unknown user');
    END IF;

    SELECT pk_post INTO v_pk_post
    FROM tb_post WHERE id = (input->>'post_id')::uuid AND status = 'published';
    IF v_pk_post IS NULL THEN
        RETURN blog_error('not_found:post', 'Post not found');
    END IF;

    IF input->>'parent_id' IS NOT NULL THEN
        SELECT pk_comment INTO v_pk_parent
        FROM tb_comment WHERE id = (input->>'parent_id')::uuid AND fk_post = v_pk_post;
        IF v_pk_parent IS NULL THEN
            RETURN blog_error('not_found:parent_comment', 'Parent comment not found on this post');
        END IF;
    END IF;

    IF coalesce(trim(input->>'content'), '') = '' THEN
        RETURN blog_error('validation:content', 'Content is required');
    END IF;

    -- New comments wait for moderation (status 'pending')
    INSERT INTO tb_comment (fk_post, fk_author, fk_parent, content)
    VALUES (v_pk_post, v_pk_author, v_pk_parent, input->>'content')
    RETURNING id INTO v_id;

    RETURN ROW(
        'created', 'Comment created', v_id::text, 'Comment',
        (SELECT data FROM v_comment WHERE id = v_id), NULL, NULL, NULL
    )::mutation_response;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION create_tag(input JSONB)
RETURNS mutation_response AS $$
DECLARE
    v_id UUID;
BEGIN
    IF coalesce(trim(input->>'name'), '') = '' THEN
        RETURN blog_error('validation:name', 'Name is required');
    END IF;
    IF EXISTS (SELECT 1 FROM tb_tag WHERE lower(name) = lower(input->>'name')) THEN
        RETURN blog_error('conflict:tag_name', 'A tag with this name already exists');
    END IF;

    INSERT INTO tb_tag (identifier, name, color, description)
    VALUES ('', input->>'name', coalesce(input->>'color', '#6366f1'), input->>'description')
    RETURNING id INTO v_id;

    RETURN ROW(
        'created', 'Tag created', v_id::text, 'Tag',
        (SELECT data FROM v_tag WHERE id = v_id), NULL, NULL, NULL
    )::mutation_response;
END;
$$ LANGUAGE plpgsql;

-- ==============================================================================
-- COMMENTS: Documentation for the Trinity pattern
-- ==============================================================================

COMMENT ON TABLE tb_user IS 'Users table with Trinity pattern: pk_user (INT, internal), id (UUID, public API), identifier (TEXT, username slug)';
COMMENT ON TABLE tb_post IS 'Posts table with Trinity pattern: pk_post (INT, internal), id (UUID, public API), identifier (TEXT, post slug)';
COMMENT ON TABLE tb_tag IS 'Tags table with Trinity pattern: pk_tag (INT, internal), id (UUID, public API), identifier (TEXT, tag slug)';
COMMENT ON TABLE tb_comment IS 'Comments table with Trinity pattern: pk_comment (INT, internal), id (UUID, public API), identifier (TEXT, optional)';

COMMENT ON COLUMN tb_user.pk_user IS 'Internal primary key (INT) for joins - never exposed in GraphQL';
COMMENT ON COLUMN tb_user.id IS 'Public UUID identifier for the GraphQL API';
COMMENT ON COLUMN tb_user.identifier IS 'Human-readable username slug for URLs';
