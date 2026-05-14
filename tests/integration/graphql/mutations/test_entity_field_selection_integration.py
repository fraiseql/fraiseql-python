"""Integration tests for nested entity field selection (GitHub issue #525).

Tests verify that mutations respect GraphQL field selection for nested entity objects,
reducing payload size and matching query behavior.
"""

import json

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
class TestEntityFieldSelectionIntegration:
    """Integration tests for entity field filtering in mutation responses."""

    @pytest.fixture(scope="class")
    async def setup_location_schema(self, class_db_pool, test_schema, clear_registry_class):
        """Set up test schema with Location entity and mutations."""
        async with class_db_pool.connection() as conn:
            await conn.execute(f"SET search_path TO {test_schema}, public")

            # Create mutation_response type
            await conn.execute(
                """
                CREATE TYPE mutation_response AS (
                    status TEXT,
                    message TEXT,
                    entity_id TEXT,
                    entity_type TEXT,
                    entity JSONB,
                    updated_fields TEXT[],
                    cascade JSONB,
                    metadata JSONB
                )
                """
            )

            # Create locations table with many fields (simulating PrintOptim)
            await conn.execute(
                """
                CREATE TABLE test_locations (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    level TEXT,
                    parent_id TEXT,
                    available_depth_mm INTEGER,
                    available_height_mm INTEGER,
                    available_width_mm INTEGER,
                    has_elevator BOOLEAN,
                    lat DOUBLE PRECISION,
                    lng DOUBLE PRECISION,
                    address_line1 TEXT,
                    address_line2 TEXT,
                    city TEXT,
                    postal_code TEXT,
                    country TEXT,
                    path_of_ids TEXT[],
                    path_of_names TEXT[],
                    metadata JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )

            # Create nested address table for testing deep nesting
            await conn.execute(
                """
                CREATE TABLE test_addresses (
                    id TEXT PRIMARY KEY,
                    location_id TEXT REFERENCES test_locations(id),
                    formatted TEXT,
                    street TEXT,
                    city TEXT,
                    postal_code TEXT,
                    country TEXT,
                    latitude DOUBLE PRECISION,
                    longitude DOUBLE PRECISION,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )

            # Create function that returns location with ALL fields
            await conn.execute(
                f"""
                CREATE OR REPLACE FUNCTION {test_schema}.create_location(input_payload JSONB)
                RETURNS mutation_response AS $$
                DECLARE
                    new_id TEXT;
                    location_name TEXT;
                    location_data JSONB;
                BEGIN
                    location_name := input_payload->>'name';
                    new_id := gen_random_uuid()::TEXT;

                    INSERT INTO test_locations (
                        id, name, level, available_depth_mm, available_height_mm,
                        available_width_mm, has_elevator, lat, lng,
                        address_line1, city, postal_code, country
                    )
                    VALUES (
                        new_id,
                        location_name,
                        'floor-1',
                        1000,
                        2000,
                        3000,
                        TRUE,
                        48.8606,
                        2.3376,
                        '123 Main St',
                        'Paris',
                        '75001',
                        'France'
                    )
                    RETURNING to_jsonb(test_locations.*) INTO location_data;

                    RETURN ROW(
                        'created',
                        'Location created successfully',
                        new_id,
                        'Location',
                        location_data,
                        ARRAY['name', 'city'],
                        NULL,
                        NULL
                    )::mutation_response;
                END;
                $$ LANGUAGE plpgsql;
                """
            )

            # Create function that returns location with nested address
            await conn.execute(
                f"""
                CREATE OR REPLACE FUNCTION {test_schema}.create_location_with_address(input_payload JSONB)
                RETURNS mutation_response AS $$
                DECLARE
                    new_loc_id TEXT;
                    new_addr_id TEXT;
                    location_name TEXT;
                    location_data JSONB;
                    address_data JSONB;
                    combined_data JSONB;
                BEGIN
                    location_name := input_payload->>'name';
                    new_loc_id := gen_random_uuid()::TEXT;
                    new_addr_id := gen_random_uuid()::TEXT;

                    -- Create location
                    INSERT INTO test_locations (
                        id, name, level, city, country
                    )
                    VALUES (
                        new_loc_id,
                        location_name,
                        'floor-1',
                        'Paris',
                        'France'
                    )
                    RETURNING to_jsonb(test_locations.*) INTO location_data;

                    -- Create address
                    INSERT INTO test_addresses (
                        id, location_id, formatted, street, city, postal_code, country,
                        latitude, longitude
                    )
                    VALUES (
                        new_addr_id,
                        new_loc_id,
                        '123 Main St, Paris 75001, France',
                        '123 Main St',
                        'Paris',
                        '75001',
                        'France',
                        48.8606,
                        2.3376
                    )
                    RETURNING to_jsonb(test_addresses.*) INTO address_data;

                    -- Combine location with nested address
                    combined_data := location_data || jsonb_build_object('address', address_data);

                    RETURN ROW(
                        'created',
                        'Location with address created',
                        new_loc_id,
                        'Location',
                        combined_data,
                        ARRAY['name'],
                        NULL,
                        NULL
                    )::mutation_response;
                END;
                $$ LANGUAGE plpgsql;
                """
            )

            await conn.commit()

    async def test_entity_field_selection_filters_simple_fields(
        self, db_connection, setup_location_schema, test_schema
    ):
        """Verify that entity field selection filters simple fields (GitHub issue #525)."""
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from fraiseql.mutations.rust_executor import execute_mutation_rust

        # Create mock info object with field selections
        # Simulates GraphQL query: location { id, name }
        info = MagicMock()

        # Mock field nodes for entity selection extraction
        # This would normally be parsed from the actual GraphQL query
        location_field = MagicMock()
        location_field.name.value = "location"
        location_field.selection_set = MagicMock()

        id_field = MagicMock()
        id_field.name.value = "id"
        id_field.selection_set = None

        name_field = MagicMock()
        name_field.name.value = "name"
        name_field.selection_set = None

        location_field.selection_set.selections = [id_field, name_field]

        success_fragment = MagicMock()
        type_condition = MagicMock()
        name_mock = MagicMock()
        name_mock.value = "CreateLocationSuccess"
        type_condition.name = name_mock
        success_fragment.type_condition = type_condition
        success_fragment.selection_set = MagicMock()
        success_fragment.selection_set.selections = [location_field]

        mutation_field = MagicMock()
        mutation_field.selection_set = MagicMock()
        mutation_field.selection_set.selections = [success_fragment]

        info.field_nodes = [mutation_field]

        # Extract entity selections using our implementation
        from fraiseql.mutations.mutation_decorator import _extract_entity_field_selections

        entity_selections = _extract_entity_field_selections(
            info, "CreateLocationSuccess", "location"
        )
        entity_selections_json = json.dumps(entity_selections) if entity_selections else None

        config = SimpleNamespace(auto_camel_case=True)

        # Execute mutation
        result = await execute_mutation_rust(
            conn=db_connection,
            function_name=f"{test_schema}.create_location",
            input_data={"name": "Test Warehouse"},
            field_name="createLocation",
            success_type="CreateLocationSuccess",
            error_type="CreateLocationError",
            entity_field_name="location",
            entity_type="Location",
            config=config,
            success_type_fields=["location"],  # Only select location field
            error_type_fields=None,
            entity_selections=entity_selections_json,  # Apply entity filtering
        )

        # Parse response using to_json() method for testing
        response = result.to_json()
        data = response["data"]["createLocation"]
        location = data["location"]

        # Should have only requested fields
        assert "id" in location, "id field should be present"
        assert "name" in location, "name field should be present"
        assert location["name"] == "Test Warehouse"

        # Should NOT have unrequested fields (GitHub issue #525 fix)
        assert "level" not in location, "level should be filtered out"
        assert "availableDepthMm" not in location, "availableDepthMm should be filtered out"
        assert "availableHeightMm" not in location, "availableHeightMm should be filtered out"
        assert "hasElevator" not in location, "hasElevator should be filtered out"
        assert "lat" not in location, "lat should be filtered out"
        assert "lng" not in location, "lng should be filtered out"
        assert "addressLine1" not in location, "addressLine1 should be filtered out"
        assert "city" not in location, "city should be filtered out"
        assert "postalCode" not in location, "postalCode should be filtered out"

        print(f"✅ Entity field filtering works! Only returned: {list(location.keys())}")
        print(f"✅ Filtered out {20 - len(location)} unrequested fields")

    async def test_entity_field_selection_nested_objects(
        self, db_connection, setup_location_schema, test_schema
    ):
        """Verify that entity field selection works for nested objects."""
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from fraiseql.mutations.rust_executor import execute_mutation_rust

        # Create mock info with nested selections
        # Simulates: location { id, name, address { id, city } }
        info = MagicMock()

        # Create address field with sub-selections
        addr_id_field = MagicMock()
        addr_id_field.name.value = "id"
        addr_id_field.selection_set = None

        addr_city_field = MagicMock()
        addr_city_field.name.value = "city"
        addr_city_field.selection_set = None

        address_field = MagicMock()
        address_field.name.value = "address"
        address_field.selection_set = MagicMock()
        address_field.selection_set.selections = [addr_id_field, addr_city_field]

        # Create location fields
        id_field = MagicMock()
        id_field.name.value = "id"
        id_field.selection_set = None

        name_field = MagicMock()
        name_field.name.value = "name"
        name_field.selection_set = None

        location_field = MagicMock()
        location_field.name.value = "location"
        location_field.selection_set = MagicMock()
        location_field.selection_set.selections = [id_field, name_field, address_field]

        success_fragment = MagicMock()
        type_condition = MagicMock()
        name_mock = MagicMock()
        name_mock.value = "CreateLocationSuccess"
        type_condition.name = name_mock
        success_fragment.type_condition = type_condition
        success_fragment.selection_set = MagicMock()
        success_fragment.selection_set.selections = [location_field]

        mutation_field = MagicMock()
        mutation_field.selection_set = MagicMock()
        mutation_field.selection_set.selections = [success_fragment]

        info.field_nodes = [mutation_field]

        # Extract entity selections
        from fraiseql.mutations.mutation_decorator import _extract_entity_field_selections

        entity_selections = _extract_entity_field_selections(
            info, "CreateLocationSuccess", "location"
        )
        entity_selections_json = json.dumps(entity_selections) if entity_selections else None

        config = SimpleNamespace(auto_camel_case=True)

        # Execute mutation with nested entity
        result = await execute_mutation_rust(
            conn=db_connection,
            function_name=f"{test_schema}.create_location_with_address",
            input_data={"name": "Warehouse with Address"},
            field_name="createLocation",
            success_type="CreateLocationSuccess",
            error_type="CreateLocationError",
            entity_field_name="location",
            entity_type="Location",
            config=config,
            success_type_fields=["location"],
            error_type_fields=None,
            entity_selections=entity_selections_json,
        )

        # Parse response using to_json() method for testing
        response = result.to_json()
        data = response["data"]["createLocation"]
        location = data["location"]

        # Top-level fields
        assert "id" in location
        assert "name" in location
        assert "address" in location

        # Nested address should be filtered
        address = location["address"]
        assert "id" in address, "address.id should be present"
        assert "city" in address, "address.city should be present"
        assert address["city"] == "Paris"

        # Unrequested nested fields should be filtered
        assert "formatted" not in address, "address.formatted should be filtered out"
        assert "street" not in address, "address.street should be filtered out"
        assert "postalCode" not in address, "address.postalCode should be filtered out"
        assert "country" not in address, "address.country should be filtered out"
        assert "latitude" not in address, "address.latitude should be filtered out"
        assert "longitude" not in address, "address.longitude should be filtered out"

        print("✅ Nested entity filtering works!")
        print(f"   Location fields: {list(location.keys())}")
        print(f"   Address fields: {list(address.keys())}")

    async def test_backward_compat_no_entity_selections(
        self, db_connection, setup_location_schema, test_schema
    ):
        """Verify backward compatibility: No entity_selections = return all fields."""
        from types import SimpleNamespace

        from fraiseql.mutations.rust_executor import execute_mutation_rust

        config = SimpleNamespace(auto_camel_case=True)

        # Execute mutation WITHOUT entity_selections parameter
        result = await execute_mutation_rust(
            conn=db_connection,
            function_name=f"{test_schema}.create_location",
            input_data={"name": "Test Location"},
            field_name="createLocation",
            success_type="CreateLocationSuccess",
            error_type="CreateLocationError",
            entity_field_name="location",
            entity_type="Location",
            config=config,
            success_type_fields=None,
            error_type_fields=None,
            entity_selections=None,  # No filtering
        )

        # Parse response using to_json() method for testing
        response = result.to_json()
        data = response["data"]["createLocation"]
        location = data["location"]

        # Should have ALL fields (backward compatible)
        assert "id" in location
        assert "name" in location
        assert "level" in location
        assert "availableDepthMm" in location
        assert "hasElevator" in location
        assert "lat" in location
        assert "lng" in location
        assert "city" in location

        print(f"✅ Backward compatibility: All {len(location)} fields returned when no filtering")

    async def test_empty_entity_selection_returns_all_fields(
        self, db_connection, setup_location_schema, test_schema
    ):
        """Verify empty selection {} returns all fields (GraphQL spec)."""
        from types import SimpleNamespace

        from fraiseql.mutations.rust_executor import execute_mutation_rust

        config = SimpleNamespace(auto_camel_case=True)

        # Empty selection = GraphQL default behavior (all fields)
        entity_selections_json = json.dumps({"fields": []})

        result = await execute_mutation_rust(
            conn=db_connection,
            function_name=f"{test_schema}.create_location",
            input_data={"name": "Test Location"},
            field_name="createLocation",
            success_type="CreateLocationSuccess",
            error_type="CreateLocationError",
            entity_field_name="location",
            entity_type="Location",
            config=config,
            success_type_fields=None,
            error_type_fields=None,
            entity_selections=entity_selections_json,  # Empty selection
        )

        # Parse response using to_json() method for testing
        response = result.to_json()
        data = response["data"]["createLocation"]
        location = data["location"]

        # Empty selection should return all fields
        assert "id" in location
        assert "name" in location
        assert "city" in location

        print("✅ Empty selection returns all fields (GraphQL spec)")
