-- ============================================================================
-- Pattern: Bulk Operations
-- ============================================================================
-- Use Case: Process multiple items in a single mutation
-- Benefits: Atomic operations, better performance, consistent error handling
--
-- This example shows:
-- - Processing arrays of input data
-- - Collecting results/errors for each item
-- - Atomic success or rollback
-- - Partial success handling
-- ============================================================================

CREATE OR REPLACE FUNCTION bulk_create_users(input_payload jsonb)
RETURNS mutation_response AS $$
DECLARE
    result mutation_response;
    users_data jsonb;
    user_data jsonb;
    success_count int := 0;
    error_count int := 0;
    results jsonb := '[]'::jsonb;
    errors jsonb := '[]'::jsonb;
    user_record record;
BEGIN
    -- ========================================================================
    -- Extract Input Array
    -- ========================================================================

    users_data := input_payload->'users';
    IF users_data IS NULL OR jsonb_typeof(users_data) != 'array' THEN
        result.status := 'failed:validation';
        result.message := 'Users array is required';
        RETURN result;
    END IF;

    -- ========================================================================
    -- Process Each User
    -- ========================================================================

    FOR user_data IN SELECT jsonb_array_elements(users_data)
    LOOP
        BEGIN
            -- Extract user fields
            DECLARE
                user_email text := user_data->>'email';
                user_name text := user_data->>'name';
            BEGIN
                -- Validate this user
                IF user_email IS NULL OR trim(user_email) = '' THEN
                    errors := errors || build_error_object(
                        422, 'email_required', 'Email is required',
                        jsonb_build_object('user_data', user_data)
                    );
                    error_count := error_count + 1;
                    CONTINUE;
                END IF;

                IF user_name IS NULL OR trim(user_name) = '' THEN
                    errors := errors || build_error_object(
                        422, 'name_required', 'Name is required',
                        jsonb_build_object('user_data', user_data)
                    );
                    error_count := error_count + 1;
                    CONTINUE;
                END IF;

                -- Check for duplicate email
                IF EXISTS (SELECT 1 FROM users WHERE email = user_email) THEN
                    errors := errors || build_error_object(
                        409, 'duplicate_email', 'Email already exists',
                        jsonb_build_object('email', user_email, 'user_data', user_data)
                    );
                    error_count := error_count + 1;
                    CONTINUE;
                END IF;

                -- Create user
                INSERT INTO users (email, name)
                VALUES (user_email, user_name)
                RETURNING * INTO user_record;

                -- Add to success results
                results := results || jsonb_build_object(
                    'success', true,
                    'user', row_to_json(user_record),
                    'input', user_data
                );
                success_count := success_count + 1;
            END;

        EXCEPTION
            WHEN OTHERS THEN
                errors := errors || build_error_object(
                    500, 'processing_error', SQLERRM,
                    jsonb_build_object('user_data', user_data)
                );
                error_count := error_count + 1;
        END;
    END LOOP;

    -- ========================================================================
    -- Build Response
    -- ========================================================================

    IF error_count > 0 AND success_count = 0 THEN
        -- Complete failure
        result.status := 'failed:validation';
        result.message := format('All %s users failed validation', error_count);
        result.metadata := jsonb_build_object('errors', errors);
        RETURN result;
    ELSIF error_count > 0 AND success_count > 0 THEN
        -- Partial success
        result.status := 'created';
        result.message := format('Created %s users, %s failed', success_count, error_count);
        result.metadata := jsonb_build_object(
            'results', results,
            'errors', errors,
            'summary', jsonb_build_object(
                'success_count', success_count,
                'error_count', error_count
            )
        );
        RETURN result;
    ELSE
        -- Complete success
        result.status := 'created';
        result.message := format('Successfully created %s users', success_count);
        result.metadata := jsonb_build_object(
            'results', results,
            'summary', jsonb_build_object(
                'success_count', success_count,
                'error_count', 0
            )
        );
        RETURN result;
    END IF;

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

-- Complete success
SELECT * FROM bulk_create_users('{
    "users": [
        {"email": "bulk1@example.com", "name": "Bulk User 1"},
        {"email": "bulk2@example.com", "name": "Bulk User 2"},
        {"email": "bulk3@example.com", "name": "Bulk User 3"}
    ]
}'::jsonb);
-- Returns: status='created', metadata with 3 successful results

-- Partial success: the second user's email already exists, the third has none
SELECT * FROM bulk_create_users('{
    "users": [
        {"email": "partial1@example.com", "name": "Partial User 1"},
        {"email": "john@example.com", "name": "Duplicate Email"},
        {"email": "", "name": "No Email"},
        {"email": "partial2@example.com", "name": "Partial User 2"}
    ]
}'::jsonb);
-- Returns: status='created', metadata with 2 successes and 2 errors

-- Complete failure
SELECT * FROM bulk_create_users('{
    "users": [
        {"email": "", "name": ""},
        {"email": "john@example.com", "name": "Duplicate"}
    ]
}'::jsonb);
-- Returns: status='failed:validation', metadata with all errors

-- ============================================================================
-- Alternative: Bulk Update Pattern
-- ============================================================================

CREATE OR REPLACE FUNCTION bulk_update_user_status(input_payload jsonb)
RETURNS mutation_response AS $$
DECLARE
    result mutation_response;
    user_ids jsonb;
    new_status text;
    updated_count int;
BEGIN
    user_ids := input_payload->'user_ids';
    new_status := input_payload->>'status';

    -- Validate status
    IF new_status NOT IN ('active', 'inactive', 'suspended') THEN
        result.status := 'failed:validation';
        result.message := 'Invalid status. Must be: active, inactive, or suspended';
        RETURN result;
    END IF;

    -- Bulk update
    UPDATE users SET
        status = new_status,
        updated_at = now()
    WHERE id = ANY(ARRAY(SELECT jsonb_array_elements_text(user_ids)::uuid))
    AND status != new_status;  -- Only update if different

    GET DIAGNOSTICS updated_count = ROW_COUNT;

    result.status := 'updated';
    result.message := format('Updated status for %s users', updated_count);
    result.metadata := jsonb_build_object(
        'updated_count', updated_count,
        'new_status', new_status
    );

    RETURN result;

EXCEPTION
    WHEN OTHERS THEN
        result.status := 'failed:error';
        result.message := SQLERRM;
        RETURN result;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- Bulk Update Usage
-- ============================================================================

-- Update multiple users to inactive
SELECT * FROM bulk_update_user_status('{
    "user_ids": ["550e8400-e29b-41d4-a716-446655440000", "550e8400-e29b-41d4-a716-446655440001"],
    "status": "inactive"
}'::jsonb);
-- Returns: status='updated', metadata with updated_count
