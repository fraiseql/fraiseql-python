"""Users subgraph schema - owns User entity"""

from typing import List, Optional

from fraiseql import ID, key, type


@type
@key(fields=["id"])
class User:
    """User entity - owned by this subgraph"""
    id: ID
    email: str
    name: str
    identifier: str


@type
class Query:
    """Root query type"""

    def user(self, id: ID) -> Optional[User]:
        """Get user by ID"""

    def users(self) -> List[User]:
        """Get all users"""

    def users_by_email(self, email: str) -> Optional[User]:
        """Get user by email"""


@type
class Mutation:
    """Root mutation type"""

    def create_user(self, email: str, name: str) -> User:
        """Create a new user"""

    def update_user(
        self,
        id: ID,
        email: Optional[str] = None,
        name: Optional[str] = None
    ) -> Optional[User]:
        """Update user"""

    def delete_user(self, id: ID) -> bool:
        """Delete user"""
