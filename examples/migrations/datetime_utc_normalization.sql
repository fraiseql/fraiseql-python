-- Example migration for DateTime UTC normalization with Z suffix
-- This ensures all timestamps in JSONB are formatted as ISO 8601 with 'Z' suffix

-- Create helper function for consistent UTC formatting
CREATE OR REPLACE FUNCTION to_utc_z(ts timestamptz)
RETURNS text AS $$
BEGIN
    IF ts IS NULL THEN
        RETURN NULL;
    END IF;
    RETURN to_char(ts AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"');
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Example: Update user view with UTC normalized timestamps
CREATE OR REPLACE VIEW user_view AS
SELECT
    id,
    email,  -- For filtering
    is_active,  -- For filtering
    jsonb_build_object(
        '__typename', 'User',
        'id', id,
        'email', email,
        'name', name,
        'bio', bio,
        'is_active', is_active,
        'created_at', to_utc_z(created_at),
        'updated_at', to_utc_z(updated_at),
        'last_login_at', to_utc_z(last_login_at),
        'email_verified_at', to_utc_z(email_verified_at)
    ) AS data
FROM users;

-- Example: Update post view with nested timestamps
CREATE OR REPLACE VIEW post_view AS
SELECT
    p.id,
    p.author_id,
    p.is_published,
    p.published_at,  -- For filtering/ordering
    jsonb_build_object(
        '__typename', 'Post',
        'id', p.id,
        'title', p.title,
        'slug', p.slug,
        'content', p.content,
        'excerpt', p.excerpt,
        'tags', p.tags,
        'is_published', p.is_published,
        'view_count', p.view_count,
        'created_at', to_utc_z(p.created_at),
        'updated_at', to_utc_z(p.updated_at),
        'published_at', to_utc_z(p.published_at),
        'author', (
            SELECT jsonb_build_object(
                '__typename', 'User',
                'id', u.id,
                'name', u.name,
                'email', u.email,
                'created_at', to_utc_z(u.created_at)
            )
            FROM users u
            WHERE u.id = p.author_id
        )
    ) AS data
FROM posts p;

-- Example: Comments with timestamps in arrays
CREATE OR REPLACE VIEW comment_view AS
SELECT
    c.id,
    c.post_id,
    c.author_id,
    c.parent_id,
    jsonb_build_object(
        '__typename', 'Comment',
        'id', c.id,
        'content', c.content,
        'is_edited', c.is_edited,
        'created_at', to_utc_z(c.created_at),
        'updated_at', to_utc_z(c.updated_at),
        'edited_at', to_utc_z(c.edited_at),
        'author', (
            SELECT jsonb_build_object(
                'id', u.id,
                'name', u.name,
                'avatar_url', u.avatar_url
            )
            FROM users u
            WHERE u.id = c.author_id
        ),
        'replies', COALESCE(
            (
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'id', r.id,
                        'content', r.content,
                        'created_at', to_utc_z(r.created_at),
                        'author_name', ru.name
                    )
                    ORDER BY r.created_at
                )
                FROM comments r
                JOIN users ru ON ru.id = r.author_id
                WHERE r.parent_id = c.id
            ),
            '[]'::jsonb
        )
    ) AS data
FROM comments c
WHERE c.parent_id IS NULL;

-- Example: Activity feed with multiple timestamp fields
CREATE OR REPLACE VIEW activity_view AS
SELECT
    a.id,
    a.user_id,
    a.activity_type,
    a.occurred_at,  -- For ordering
    jsonb_build_object(
        '__typename', 'Activity',
        'id', a.id,
        'type', a.activity_type,
        'description', a.description,
        'metadata', a.metadata,
        'occurred_at', to_utc_z(a.occurred_at),
        'user', (
            SELECT jsonb_build_object(
                'id', u.id,
                'name', u.name,
                'avatar_url', u.avatar_url
            )
            FROM users u
            WHERE u.id = a.user_id
        ),
        -- Computed relative time (for reference)
        'time_ago', CASE
            WHEN a.occurred_at > NOW() - INTERVAL '1 minute' THEN 'just now'
            WHEN a.occurred_at > NOW() - INTERVAL '1 hour' THEN
                CONCAT(EXTRACT(MINUTE FROM NOW() - a.occurred_at)::INT, ' minutes ago')
            WHEN a.occurred_at > NOW() - INTERVAL '1 day' THEN
                CONCAT(EXTRACT(HOUR FROM NOW() - a.occurred_at)::INT, ' hours ago')
            ELSE to_utc_z(a.occurred_at)
        END
    ) AS data
FROM activities a
ORDER BY a.occurred_at DESC;

-- Example: Aggregated data with date grouping
CREATE OR REPLACE VIEW daily_stats_view AS
SELECT
    date_trunc('day', created_at AT TIME ZONE 'UTC') AS day,
    jsonb_build_object(
        '__typename', 'DailyStats',
        'date', to_char(date_trunc('day', created_at AT TIME ZONE 'UTC'), 'YYYY-MM-DD'),
        'day_start', to_utc_z(date_trunc('day', created_at AT TIME ZONE 'UTC')),
        'day_end', to_utc_z(date_trunc('day', created_at AT TIME ZONE 'UTC') + INTERVAL '1 day' - INTERVAL '1 second'),
        'user_count', COUNT(DISTINCT user_id),
        'post_count', COUNT(*),
        'first_post_at', to_utc_z(MIN(created_at)),
        'last_post_at', to_utc_z(MAX(created_at))
    ) AS data
FROM posts
WHERE created_at >= NOW() - INTERVAL '30 days'
GROUP BY date_trunc('day', created_at AT TIME ZONE 'UTC')
ORDER BY day DESC;

-- Test the function with various inputs
DO $$
BEGIN
    -- Test with different timezones
    RAISE NOTICE 'UTC: %', to_utc_z('2025-01-15 12:00:00+00:00'::timestamptz);
    RAISE NOTICE 'EST: %', to_utc_z('2025-01-15 12:00:00-05:00'::timestamptz);
    RAISE NOTICE 'CET: %', to_utc_z('2025-01-15 12:00:00+01:00'::timestamptz);
    RAISE NOTICE 'NULL: %', to_utc_z(NULL::timestamptz);
END $$;
