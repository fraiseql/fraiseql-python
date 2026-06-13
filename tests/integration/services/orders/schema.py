"""Orders subgraph schema - extends User, owns Order entity"""

from typing import List, Optional

from fraiseql import ID, extends, external, key, type


@extends
@key(fields=["id"])
@type
class User:
    """User extended from users subgraph"""
    id: ID = external()
    orders: List["Order"]


@type
@key(fields=["id"])
class Order:
    """Order entity - owned by this subgraph"""
    id: ID
    user_id: ID
    status: str
    total: float
    identifier: str


@type
class Query:
    """Root query type"""

    def order(self, id: ID) -> Optional[Order]:
        """Get order by ID"""

    def orders(self) -> List[Order]:
        """Get all orders"""

    def orders_by_user(self, user_id: ID) -> List[Order]:
        """Get orders for a user"""

    def orders_by_status(self, status: str) -> List[Order]:
        """Get orders by status"""


@type
class Mutation:
    """Root mutation type"""

    def create_order(self, user_id: ID, total: float) -> Order:
        """Create a new order"""

    def update_order_status(self, id: ID, status: str) -> Optional[Order]:
        """Update order status"""

    def delete_order(self, id: ID) -> bool:
        """Delete order"""
