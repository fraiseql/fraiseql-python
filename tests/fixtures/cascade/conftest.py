"""Test fixtures for GraphQL Cascade functionality.

Provides test app, client, and database setup for cascade integration tests.
"""

import asyncio
from typing import AsyncGenerator, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

# Import database fixtures
import fraiseql
from fraiseql.mutations import mutation
from fraiseql.mutations.types import Cascade


# Test types for cascade
@fraiseql.input
class CreatePostInput:
    title: str
    content: Optional[str] = None
    author_id: str


@fraiseql.type
class Post:
    id: str
    title: str
    content: Optional[str] = None
    author_id: str


@fraiseql.type
class User:
    id: str
    name: str
    post_count: int


@fraiseql.type
class CreatePostSuccess:
    id: str
    message: str
    cascade: Cascade


@fraiseql.type
class CreatePostWithEntitySuccess:
    """Success type with nested entity field - tests bug from cascade_bug_report.md."""

    post: Post
    message: str
    cascade: Cascade


@fraiseql.type
class CreatePostError:
    code: int
    message: str


@fraiseql.type
class UpdatePostTitleSuccess:
    """Success type for update mutation - returns empty CASCADE."""

    id: str
    message: str
    cascade: Cascade


@fraiseql.type
class UpdatePostTitleError:
    code: int
    message: str


# Test mutations
@mutation(enable_cascade=True)
class CreatePost:
    input: CreatePostInput
    success: CreatePostSuccess
    error: CreatePostError


@mutation(enable_cascade=True, function="create_post_with_entity")
class CreatePostWithEntity:
    """Mutation that returns entity in success type - tests CASCADE doesn't break entity fields."""

    input: CreatePostInput
    success: CreatePostWithEntitySuccess
    error: CreatePostError


@mutation(enable_cascade=True, function="update_post_title")
class UpdatePostTitle:
    """Mutation that may return empty CASCADE when no side effects occur."""

    input: CreatePostInput  # Reuse same input for simplicity
    success: UpdatePostTitleSuccess
    error: UpdatePostTitleError


@mutation(enable_cascade=True, function="create_post_with_entity")
class CreatePostEnriched:
    """Mutation whose async prepare_input takes info (issue #557).

    It shares its SQL function and result types with CreatePostWithEntity, which
    used to drop one of the two fields or fail the schema build.
    """

    input: CreatePostInput
    success: CreatePostWithEntitySuccess
    error: CreatePostError

    @staticmethod
    async def prepare_input(input_data: dict, info: "GraphQLResolveInfo") -> dict:
        await asyncio.sleep(0)
        return {**input_data, "title": f"{input_data['title']} via {info.field_name}"}


# Test query (required for GraphQL schema)
from graphql import GraphQLResolveInfo


async def get_post(info: GraphQLResolveInfo, id: str) -> Optional[Post]:
    """Simple query to satisfy GraphQL schema requirements."""
    return None  # Not needed for cascade tests


@pytest_asyncio.fixture(scope="class", loop_scope="class")
async def cascade_db_schema(
    class_db_pool, test_schema, clear_registry_class
) -> AsyncGenerator[None]:
    """Set up cascade test database schema with tables and PostgreSQL function.

    Uses the shared class_db_pool fixture from database_conftest.py for proper database access.
    Creates tables and a PostgreSQL function that returns mutation_response with cascade data.

    CRITICAL: Creates all objects in test_schema for proper isolation.
    """
    async with class_db_pool.connection() as conn:
        await conn.execute(f"SET search_path TO {test_schema}, public")
        # Create mutation_response type (from migrations/trinity/005_add_mutation_response.sql)
        await conn.execute("""
            DO $$ BEGIN
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
                WHEN duplicate_object THEN null;
            END $$;
        """)

        # Create tables in test_schema (via search_path - NO explicit public schema)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tb_user (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                post_count INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS tb_post (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT,
                author_id TEXT REFERENCES tb_user(id)
            );
        """)

        # Create PostgreSQL function in public schema (for FraiseQL default)
        await conn.execute("""
            CREATE OR REPLACE FUNCTION public.create_post(input_data JSONB)
            RETURNS mutation_response AS $$
            DECLARE
                p_title TEXT;
                p_content TEXT;
                p_author_id TEXT;
                v_post_id TEXT;
                v_cascade JSONB;
                v_entity JSONB;
            BEGIN
                -- Extract input parameters (snake_case from FraiseQL)
                p_title := input_data->>'title';
                p_content := input_data->>'content';
                p_author_id := input_data->>'author_id';

                -- Validate input
                IF p_title = '' OR p_title IS NULL THEN
                    RETURN ROW(
                        'failed:validation',
                        'Title cannot be empty',
                        NULL, NULL, NULL, NULL, NULL,
                        jsonb_build_object('field', 'title')
                    )::mutation_response;
                END IF;

                -- Check if user exists (no schema prefix - uses search_path)
                IF NOT EXISTS (SELECT 1 FROM tb_user WHERE id = p_author_id) THEN
                    RETURN ROW(
                        'failed:not_found',
                        'Author not found',
                        NULL, NULL, NULL, NULL, NULL,
                        jsonb_build_object('resource', 'User', 'id', p_author_id)
                    )::mutation_response;
                END IF;

                -- Create post
                v_post_id := 'post-' || gen_random_uuid()::text;

                INSERT INTO tb_post (id, title, content, author_id)
                VALUES (v_post_id, p_title, p_content, p_author_id);

                -- Update user post count
                UPDATE tb_user
                SET post_count = post_count + 1
                WHERE id = p_author_id;

                -- Build entity data
                v_entity := jsonb_build_object(
                    'id', v_post_id,
                    'title', p_title,
                    'content', p_content,
                    'author_id', p_author_id
                );

                -- Build cascade data per GraphQL Cascade spec
                -- Use camelCase for cascade fields (passed through as-is)
                v_cascade := jsonb_build_object(
                    'updated', jsonb_build_array(
                        jsonb_build_object(
                            '__typename', 'Post',
                            'id', v_post_id,
                            'operation', 'CREATED',
                            'entity', jsonb_build_object(
                                'id', v_post_id,
                                'title', p_title,
                                'content', p_content,
                                'authorId', p_author_id
                            )
                        ),
                        jsonb_build_object(
                            '__typename', 'User',
                            'id', p_author_id,
                            'operation', 'UPDATED',
                            'entity', (
                                SELECT jsonb_build_object(
                                    'id', id,
                                    'name', name,
                                    'postCount', post_count
                                )
                                FROM tb_user WHERE id = p_author_id
                            )
                        )
                    ),
                    'deleted', jsonb_build_array(),
                    'invalidations', jsonb_build_array(
                        jsonb_build_object(
                            'queryName', 'posts',
                            'strategy', 'INVALIDATE',
                            'scope', 'PREFIX'
                        )
                    ),
                    'metadata', jsonb_build_object(
                        'timestamp', NOW()::text,
                        'affectedCount', 2
                    )
                );

                -- Return success with cascade via mutation_response
                RETURN ROW(
                    'created',
                    'Post created successfully',
                    v_post_id,
                    'Post',
                    v_entity,
                    NULL::text[],
                    v_cascade,
                    NULL::jsonb
                )::mutation_response;
            END;
            $$ LANGUAGE plpgsql;
        """)

        # Create PostgreSQL function for mutation with entity return
        # This function returns the entity in a way that FraiseQL can map to the Post field
        await conn.execute("""
            CREATE OR REPLACE FUNCTION public.create_post_with_entity(input_data JSONB)
            RETURNS mutation_response AS $$
            DECLARE
                p_title TEXT;
                p_content TEXT;
                p_author_id TEXT;
                v_post_id TEXT;
                v_cascade JSONB;
                v_entity JSONB;
            BEGIN
                -- Extract input parameters (snake_case from FraiseQL)
                p_title := input_data->>'title';
                p_content := input_data->>'content';
                p_author_id := input_data->>'author_id';

                -- Validate input
                IF p_title = '' OR p_title IS NULL THEN
                    RETURN ROW(
                        'failed:validation',
                        'Title cannot be empty',
                        NULL, NULL, NULL, NULL, NULL,
                        jsonb_build_object('field', 'title')
                    )::mutation_response;
                END IF;

                -- Check if user exists
                IF NOT EXISTS (SELECT 1 FROM tb_user WHERE id = p_author_id) THEN
                    RETURN ROW(
                        'failed:not_found',
                        'Author not found',
                        NULL, NULL, NULL, NULL, NULL,
                        jsonb_build_object('resource', 'User', 'id', p_author_id)
                    )::mutation_response;
                END IF;

                -- Create post
                v_post_id := 'post-' || gen_random_uuid()::text;

                INSERT INTO tb_post (id, title, content, author_id)
                VALUES (v_post_id, p_title, p_content, p_author_id);

                -- Update user post count
                UPDATE tb_user
                SET post_count = post_count + 1
                WHERE id = p_author_id;

                 -- Build entity data for the Post field (this goes to CreatePostWithEntitySuccess.post)
                 -- For single entity mutations, entity should be the entity data directly
                 v_entity := jsonb_build_object(
                     'id', v_post_id,
                     'title', p_title,
                     'content', p_content,
                     'author_id', p_author_id
                 );

                -- Build cascade data
                v_cascade := jsonb_build_object(
                    'updated', jsonb_build_array(
                        jsonb_build_object(
                            '__typename', 'Post',
                            'id', v_post_id,
                            'operation', 'CREATED',
                            'entity', jsonb_build_object(
                                'id', v_post_id,
                                'title', p_title,
                                'content', p_content,
                                'authorId', p_author_id
                            )
                        ),
                        jsonb_build_object(
                            '__typename', 'User',
                            'id', p_author_id,
                            'operation', 'UPDATED',
                            'entity', (
                                SELECT jsonb_build_object(
                                    'id', id,
                                    'name', name,
                                    'postCount', post_count
                                )
                                FROM tb_user WHERE id = p_author_id
                            )
                        )
                    ),
                    'deleted', jsonb_build_array(),
                    'invalidations', jsonb_build_array(
                        jsonb_build_object(
                            'queryName', 'posts',
                            'strategy', 'INVALIDATE',
                            'scope', 'PREFIX'
                        )
                    ),
                    'metadata', jsonb_build_object(
                        'timestamp', NOW()::text,
                        'affectedCount', 2
                    )
                );

                 -- Return success with cascade
                 RETURN ROW(
                     'created',
                     'Post created successfully',
                     v_post_id,
                     'Post',  -- entity_type should be the GraphQL type name (capitalized)
                     v_entity,
                     NULL::text[],
                     v_cascade,
                     NULL
                 )::mutation_response;
            END;
            $$ LANGUAGE plpgsql;
        """)

        # Create PostgreSQL function that returns empty CASCADE
        # This simulates a mutation with no side effects
        await conn.execute("""
            CREATE OR REPLACE FUNCTION public.update_post_title(input_data JSONB)
            RETURNS mutation_response AS $$
            DECLARE
                p_title TEXT;
                p_post_id TEXT;
                v_cascade JSONB;
            BEGIN
                -- Extract input parameters
                p_title := input_data->>'title';
                p_post_id := 'post-existing';  -- Hardcoded for test

                -- Validate input
                IF p_title = '' OR p_title IS NULL THEN
                    RETURN ROW(
                        'failed:validation',
                        'Title cannot be empty',
                        NULL, NULL, NULL, NULL, NULL,
                        jsonb_build_object('field', 'title')
                    )::mutation_response;
                END IF;

                -- Build empty cascade (no side effects)
                v_cascade := jsonb_build_object(
                    'updated', jsonb_build_array(),
                    'deleted', jsonb_build_array(),
                    'invalidations', jsonb_build_array(),
                    'metadata', jsonb_build_object(
                        'timestamp', NOW()::text,
                        'affectedCount', 0
                    )
                );

                -- Return success with empty cascade
                RETURN ROW(
                    'updated',
                    'Post title updated (no side effects)',
                    p_post_id,
                    'Post',
                    jsonb_build_object(
                        'id', p_post_id,
                        'title', p_title
                    ),
                    NULL::text[],
                    v_cascade,
                    NULL
                )::mutation_response;
            END;
            $$ LANGUAGE plpgsql;
        """)

        # Insert test user (no schema prefix - uses search_path)
        await conn.execute("""
            INSERT INTO tb_user (id, name, post_count)
            VALUES ('user-123', 'Test User', 0)
            ON CONFLICT (id) DO NOTHING;
        """)
        await conn.commit()

    yield

    # Note: We intentionally skip cleanup here because:
    # 1. The tables/functions are created with IF NOT EXISTS/CREATE OR REPLACE
    # 2. The session-scoped pool may be closed before this function-scoped fixture tears down
    # 3. The test database is ephemeral (testcontainer) so cleanup is not necessary
    # This avoids async event loop issues during fixture teardown


@pytest.fixture
def cascade_app(cascade_db_schema, create_fraiseql_app_with_db) -> FastAPI:
    """FastAPI app configured with cascade mutations.

    Uses create_fraiseql_app_with_db for shared database pool.
    Depends on cascade_db_schema to ensure schema is set up.
    """
    app = create_fraiseql_app_with_db(
        types=[
            CreatePostInput,
            Post,
            User,
            CreatePostSuccess,
            CreatePostWithEntitySuccess,
            CreatePostError,
            UpdatePostTitleSuccess,
            UpdatePostTitleError,
        ],
        queries=[get_post],
        mutations=[CreatePost, CreatePostWithEntity, UpdatePostTitle, CreatePostEnriched],
    )
    return app


@pytest.fixture
def cascade_client(cascade_app: FastAPI) -> TestClient:
    """Test client for cascade app (synchronous client for simple tests).

    Note: Uses raise_server_exceptions=False to avoid event loop conflicts
    during teardown when mixing async and sync fixtures.
    """
    with TestClient(cascade_app, raise_server_exceptions=False) as client:
        yield client


@pytest_asyncio.fixture
async def cascade_http_client(cascade_app: FastAPI) -> AsyncClient:
    """Async HTTP client for cascade app (for async test scenarios).

    Uses LifespanManager to properly trigger ASGI lifespan events.
    """
    from asgi_lifespan import LifespanManager

    async with LifespanManager(cascade_app) as manager:
        transport = ASGITransport(app=manager.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@pytest.fixture
def mock_apollo_client() -> MagicMock:
    """Mock Apollo Client for cascade integration testing."""
    client = MagicMock()
    client.cache = MagicMock()
    client.cache.writeFragment = AsyncMock()
    client.cache.evict = AsyncMock()
    client.cache.identify = MagicMock(return_value="Post:123")
    return client
