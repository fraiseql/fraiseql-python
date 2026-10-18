"""Example mutations demonstrating context parameter usage."""

from uuid import UUID

import fraiseql
from fraiseql.mutations import mutation
from fraiseql.types import ID


@fraiseql.input
class CreateLocationInput:
    """Input for creating a new location."""

    name: str
    address: str
    latitude: float
    longitude: float

    def to_dict(self):
        return {
            "name": self.name,
            "address": self.address,
            "latitude": self.latitude,
            "longitude": self.longitude,
        }


@fraiseql.success
class CreateLocationSuccess:
    """Success response for location creation."""

    location_id: ID
    message: str = "Location created successfully"


@fraiseql.error
class CreateLocationError:
    """Error response for location creation."""

    message: str
    code: str


@mutation(
    function="create_location",
    schema="app",
    context_params={
        "tenant_id": "input_pk_organization",  # Maps context["tenant_id"] to first parameter
        "user": "input_created_by",  # Maps context["user"].user_id to second parameter
    },
)
class CreateLocation:
    """Create a new location with tenant isolation and user tracking."""

    input: CreateLocationInput
    success: CreateLocationSuccess
    error: CreateLocationError


@fraiseql.input
class UpdateLocationInput:
    """Input for updating a location."""

    id: ID
    name: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    def to_dict(self):
        data = {"id": str(self.id)}
        if self.name is not None:
            data["name"] = self.name
        if self.address is not None:
            data["address"] = self.address
        if self.latitude is not None:
            data["latitude"] = self.latitude
        if self.longitude is not None:
            data["longitude"] = self.longitude
        return data


@fraiseql.success
class UpdateLocationSuccess:
    """Success response for location update."""

    location_id: ID
    updated_fields: list[str]
    message: str = "Location updated successfully"


@fraiseql.error
class UpdateLocationError:
    """Error response for location update."""

    message: str
    code: str


@mutation(
    function="update_location",
    schema="app",
    context_params={"tenant_id": "input_pk_organization", "user": "input_updated_by"},
)
class UpdateLocation:
    """Update an existing location with tenant isolation."""

    input: UpdateLocationInput
    success: UpdateLocationSuccess
    error: UpdateLocationError


@fraiseql.input
class DeleteLocationInput:
    """Input for deleting a location."""

    id: ID

    def to_dict(self):
        return {"id": str(self.id)}


@fraiseql.success
class DeleteLocationSuccess:
    """Success response for location deletion."""

    location_id: ID
    message: str = "Location deleted successfully"


@fraiseql.error
class DeleteLocationError:
    """Error response for location deletion."""

    message: str
    code: str


@mutation(
    function="delete_location",
    schema="app",
    context_params={"tenant_id": "input_pk_organization", "user": "input_deleted_by"},
)
class DeleteLocation:
    """Delete a location with tenant isolation and audit trail."""

    input: DeleteLocationInput
    success: DeleteLocationSuccess
    error: DeleteLocationError


# Example of mutation without context parameters (legacy style)
@fraiseql.input
class CreateCategoryInput:
    """Input for creating a category (legacy single-parameter style)."""

    name: str
    description: str
    tenant_id: ID  # Included in business data (not ideal)
    created_by: UUID

    def to_dict(self):
        return {
            "name": self.name,
            "description": self.description,
            "tenant_id": str(self.tenant_id),
            "created_by": str(self.created_by),
        }


@fraiseql.success
class CreateCategorySuccess:
    """Success response for category creation."""

    category_id: ID
    message: str = "Category created successfully"


@fraiseql.error
class CreateCategoryError:
    """Error response for category creation."""

    message: str
    code: str


@mutation(
    function="create_category",
    schema="app",
    # No context_params - uses legacy single JSONB parameter
)
class CreateCategory:
    """Create a category using legacy single-parameter style."""

    input: CreateCategoryInput
    success: CreateCategorySuccess
    error: CreateCategoryError
