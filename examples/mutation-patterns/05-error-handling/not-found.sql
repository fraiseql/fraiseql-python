-- ============================================================================
-- Pattern: Not Found Error Handling
-- ============================================================================
-- Use Case: Proper 404 error responses for missing resources
-- Benefits: Clear error messages, consistent API behavior
--
-- This example shows:
-- - Proper not_found status patterns
-- - Different identifiers for different resource types
-- - Consistent error messaging
-- ============================================================================

CREATE OR REPLACE FUNCTION get_user_details(input_payload jsonb)
RETURNS mutation_response AS $$
DECLARE
    result mutation_response;
    user_id uuid;
    user_record record;
BEGIN
    -- ========================================================================
    -- Extract Input
    -- ========================================================================

    user_id := (input_payload->>'id')::uuid;

    -- ========================================================================
    -- Find User
    -- ========================================================================

    SELECT * INTO user_record FROM users WHERE id = user_id;
    IF NOT FOUND THEN
        result.status := 'not_found:user';
        result.message := format('User with ID %s not found', user_id);
        RETURN result;
    END IF;

    -- ========================================================================
    -- Additional Checks (User-specific)
    -- ========================================================================

    -- Check if user is active
    IF user_record.status != 'active' THEN
        result.status := 'not_found:user';
        result.message := format('User %s is not active', user_id);
        RETURN result;
    END IF;

    -- ========================================================================
    -- Success Response
    -- ========================================================================

    result.status := 'success';
    result.message := 'User details retrieved successfully';
    result.entity := row_to_json(user_record);
    result.entity_id := user_record.id::text;
    result.entity_type := 'User';

    RETURN result;

EXCEPTION
    WHEN OTHERS THEN
        result.status := 'failed:error';
        result.message := SQLERRM;
        RETURN result;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- Pattern: Multiple Resource Types
-- ============================================================================

CREATE OR REPLACE FUNCTION add_comment(input_payload jsonb)
RETURNS mutation_response AS $$
DECLARE
    result mutation_response;
    post_id uuid;
    user_id uuid;
    comment_content text;
    comment_record record;
BEGIN
    post_id := (input_payload->>'post_id')::uuid;
    user_id := (input_payload->>'user_id')::uuid;
    comment_content := input_payload->>'content';

    -- Check if post exists
    IF NOT EXISTS (SELECT 1 FROM posts WHERE id = post_id) THEN
        result.status := 'not_found:post';
        result.message := format('Post with ID %s not found', post_id);
        RETURN result;
    END IF;

    -- Check if user exists
    IF NOT EXISTS (SELECT 1 FROM users WHERE id = user_id) THEN
        result.status := 'not_found:user';
        result.message := format('User with ID %s not found', user_id);
        RETURN result;
    END IF;

    -- Validate content
    IF comment_content IS NULL OR trim(comment_content) = '' THEN
        result.status := 'failed:validation';
        result.message := 'Comment content is required';
        RETURN result;
    END IF;

    -- Create comment
    INSERT INTO comments (post_id, user_id, content)
    VALUES (post_id, user_id, comment_content)
    RETURNING * INTO comment_record;

    result.status := 'created';
    result.message := 'Comment added successfully';
    result.entity := row_to_json(comment_record);
    result.entity_id := comment_record.id::text;
    result.entity_type := 'Comment';

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

-- User not found
SELECT * FROM get_user_details('{
    "id": "00000000-0000-0000-0000-000000000000"
}'::jsonb);
-- Returns: status='not_found:user', message='User with ID 00000000-0000-0000-0000-000000000000 not found'

-- User exists but inactive
-- First make a user inactive, then test
-- Returns: status='not_found:user', message='User 550e8400-e29b-41d4-a716-446655440000 is not active'

-- Post not found when adding comment
SELECT * FROM add_comment('{
    "post_id": "00000000-0000-0000-0000-000000000000",
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "content": "Great post!"
}'::jsonb);
-- Returns: status='not_found:post', message='Post with ID 00000000-0000-0000-0000-000000000000 not found'

-- User not found when adding comment
SELECT * FROM add_comment('{
    "post_id": "660e8400-e29b-41d4-a716-446655440000",
    "user_id": "00000000-0000-0000-0000-000000000000",
    "content": "Great post!"
}'::jsonb);
-- Returns: status='not_found:user', message='User with ID 00000000-0000-0000-0000-000000000000 not found'

-- Success case
SELECT * FROM add_comment('{
    "post_id": "660e8400-e29b-41d4-a716-446655440000",
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "content": "This is a great post!"
}'::jsonb);
-- Returns: status='created', entity with comment data
