-- ============================================================================
-- Pattern: Simple Validation (Pattern 1)
-- ============================================================================
-- Use Case: Basic validation with auto-generated errors
-- Benefits: Simple, minimal code, automatic error formatting
--
-- This example shows:
-- - Basic input validation
-- - Pattern 1: Simple status strings
-- - Auto-generated errors array
-- - Single error per response
-- ============================================================================

CREATE OR REPLACE FUNCTION create_post(input_payload jsonb)
RETURNS mutation_response AS $$
DECLARE
    result mutation_response;
    post_title text;
    post_content text;
    user_id uuid;
    post_record record;
BEGIN
    -- ========================================================================
    -- Extract Input
    -- ========================================================================

    post_title := input_payload->>'title';
    post_content := input_payload->>'content';
    user_id := (input_payload->>'user_id')::uuid;

    -- ========================================================================
    -- Simple Validation (Pattern 1)
    -- ========================================================================

    -- Title required
    IF post_title IS NULL OR trim(post_title) = '' THEN
        result.status := 'failed:validation';
        result.message := 'Post title is required';
        RETURN result;
    END IF;

    -- Title length check
    IF length(post_title) < 3 THEN
        result.status := 'failed:validation';
        result.message := 'Post title must be at least 3 characters';
        RETURN result;
    END IF;

    -- Content required
    IF post_content IS NULL OR trim(post_content) = '' THEN
        result.status := 'failed:validation';
        result.message := 'Post content is required';
        RETURN result;
    END IF;

    -- User exists
    IF NOT EXISTS (SELECT 1 FROM users WHERE id = user_id) THEN
        result.status := 'not_found:user';
        result.message := format('User %s not found', user_id);
        RETURN result;
    END IF;

    -- ========================================================================
    -- Create Post
    -- ========================================================================

    INSERT INTO posts (user_id, title, content)
    VALUES (user_id, post_title, post_content)
    RETURNING * INTO post_record;

    -- ========================================================================
    -- Success Response
    -- ========================================================================

    result.status := 'created';
    result.message := 'Post created successfully';
    result.entity := row_to_json(post_record);
    result.entity_id := post_record.id::text;
    result.entity_type := 'Post';

    RETURN result;

EXCEPTION
    WHEN OTHERS THEN
        result.status := 'failed:error';
        result.message := SQLERRM;
        RETURN result;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- Usage Examples
-- ============================================================================

-- Success case
SELECT * FROM create_post('{
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "title": "My First Post",
    "content": "This is the content of my post."
}'::jsonb);
-- Returns: status='created', entity with post data

-- Validation error - missing title
SELECT * FROM create_post('{
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "content": "This is the content of my post."
}'::jsonb);
-- Returns: status='failed:validation', message='Post title is required'

-- Validation error - title too short
SELECT * FROM create_post('{
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "title": "Hi",
    "content": "This is the content of my post."
}'::jsonb);
-- Returns: status='failed:validation', message='Post title must be at least 3 characters'

-- Not found error - user doesn't exist
SELECT * FROM create_post('{
    "user_id": "00000000-0000-0000-0000-000000000000",
    "title": "My First Post",
    "content": "This is the content of my post."
}'::jsonb);
-- Returns: status='not_found:user', message='User 00000000-0000-0000-0000-000000000000 not found'
