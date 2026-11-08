---
title: Bounded Contexts
description: Domain-driven design with schema separation and context boundaries
tags:
  - bounded-contexts
  - DDD
  - domain
  - architecture
  - design
---

# Bounded Contexts & DDD

Domain-Driven Design patterns in FraiseQL: bounded contexts, repositories, aggregates, and integration strategies for complex domain models.

## Overview

Bounded contexts are explicit boundaries within which a domain model is defined. FraiseQL supports DDD patterns through repositories, schema organization, and context integration.

**Key Concepts:**

- Repository pattern per bounded context
- Database schema per context (tb_*, tv_* patterns)
- Context integration patterns
- Shared kernel (common types)
- Anti-corruption layers
- Event-driven communication

## Bounded Context Design

### What is a Bounded Context?

A bounded context is an explicit boundary within which a particular domain model is defined and applicable. Different contexts can have different models of the same concept.

**Example: E-commerce System**

```
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│  Orders Context     │     │  Catalog Context    │     │  Billing Context    │
│                     │     │                     │     │                     │
│  - Order           │     │  - Product          │     │  - Invoice          │
│  - OrderItem       │     │  - Category         │     │  - Payment          │
│  - Customer        │     │  - Inventory        │     │  - Transaction      │
│  - Shipment        │────▶│  - Price            │────▶│  - Customer         │
│                     │     │                     │     │                     │
└─────────────────────┘     └─────────────────────┘     └─────────────────────┘
```

**Same entity, different models:**

- Orders Context: Customer (name, shipping address, order history)
- Catalog Context: Customer (preferences, viewed products, cart)
- Billing Context: Customer (billing address, payment methods, credit)

### Identifying Bounded Contexts

Questions to ask:

1. Does this concept mean different things in different parts of the system?
2. Do different teams own different parts of the domain?
3. Would changes in one area require changes in another?
4. Is there natural data privacy/security boundary?

**Example Contexts:**

```
Organization Management Context:
- Organizations, Users, Roles, Permissions

Order Processing Context:
- Orders, OrderItems, Fulfillment, Shipping

Inventory Context:
- Products, Stock, Warehouses, Transfers

Billing Context:
- Invoices, Payments, Subscriptions, Refunds

Analytics Context:
- Reports, Dashboards, Metrics, Events
```

## Repository Pattern

### Base Repository

FraiseQL repositories encapsulate database access per bounded context:

```python
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from fraiseql.types import ID

T = TypeVar('T')

class Repository(ABC, Generic[T]):
    """Base repository for domain entities."""

    def __init__(self, db_pool: AsyncConnectionPool, schema: str = "public"):
        # e.g. info.context["db"].get_pool(), or
        # fraiseql.fastapi.dependencies.get_db_pool()
        self.db = db_pool
        self.schema = schema
        self.table_name = self._get_table_name()

    @abstractmethod
    def _get_table_name(self) -> str:
        """Get table name for this repository."""
        pass

    @property
    def _table(self) -> sql.Identifier:
        return sql.Identifier(self.schema, self.table_name)

    async def get_by_id(self, id: ID) -> T | None:
        """Get entity by ID."""
        async with self.db.connection() as conn:
            cur = await conn.cursor(row_factory=dict_row).execute(
                sql.SQL("SELECT * FROM {} WHERE id = %s").format(self._table),
                (id,)
            )
            row = await cur.fetchone()
            return self._map_to_entity(row) if row else None

    async def get_all(self, limit: int = 100) -> list[T]:
        """Get all entities."""
        async with self.db.connection() as conn:
            cur = await conn.cursor(row_factory=dict_row).execute(
                sql.SQL("SELECT * FROM {} LIMIT %s").format(self._table),
                (limit,)
            )
            return [self._map_to_entity(row) for row in await cur.fetchall()]

    async def save(self, entity: T) -> T:
        """Save entity (insert or update)."""
        # Implemented by subclasses
        raise NotImplementedError

    async def delete(self, id: ID) -> bool:
        """Delete entity by ID."""
        # The pool commits when the block exits without an exception
        async with self.db.connection() as conn:
            cur = await conn.execute(
                sql.SQL("DELETE FROM {} WHERE id = %s").format(self._table),
                (id,)
            )
            return cur.rowcount > 0

    @abstractmethod
    def _map_to_entity(self, row) -> T:
        """Map database row to entity."""
        pass
```

### Context-Specific Repository

```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from fraiseql.types import ID

# Orders Context Domain Model
@dataclass
class Order:
    """Order aggregate root."""
    id: ID
    customer_id: ID
    items: list['OrderItem']
    total: Decimal
    status: str
    created_at: datetime
    updated_at: datetime

@dataclass
class OrderItem:
    """Order line item."""
    id: ID
    order_id: ID
    product_id: ID
    quantity: int
    price: Decimal
    total: Decimal
```

## Schema Organization

### Schema Per Context

Organize PostgreSQL schemas to match bounded contexts:

```sql
-- Orders Context
CREATE SCHEMA IF NOT EXISTS orders;

CREATE TABLE orders.tb_order (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID NOT NULL,
    total DECIMAL(10, 2) NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE orders.tb_order_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID NOT NULL REFERENCES orders.tb_order(id),
    product_id UUID NOT NULL,
    quantity INT NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    total DECIMAL(10, 2) NOT NULL
);

-- Catalog Context
CREATE SCHEMA IF NOT EXISTS catalog;

CREATE TABLE catalog.products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    category_id UUID,
    price DECIMAL(10, 2) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE catalog.categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    parent_id UUID REFERENCES catalog.categories(id)
);

-- Billing Context
CREATE SCHEMA IF NOT EXISTS billing;

CREATE TABLE billing.invoices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID NOT NULL,  -- Reference to orders context
    customer_id UUID NOT NULL,
    amount DECIMAL(10, 2) NOT NULL,
    status TEXT NOT NULL,
    due_date DATE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE billing.payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id UUID NOT NULL REFERENCES billing.invoices(id),
    amount DECIMAL(10, 2) NOT NULL,
    payment_method TEXT NOT NULL,
    transaction_id TEXT,
    paid_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Table Naming Conventions

FraiseQL conventions for bounded contexts:

```
Pattern: {schema}.{prefix}_{entity}

Examples:
- orders.tb_order          (table: order)
- orders.tv_order_summary  (view: order summary)
- catalog.tb_product       (table: product)
- catalog.tv_product_stats (view: product statistics)
- billing.tb_invoice       (table: invoice)
- billing.tv_payment_history (view: payment history)
```

**Prefixes:**

- `tb_` - Tables (base data)
- `tv_` - Views (derived data)
- `tf_` - Functions (stored procedures)
- `tt_` - Types (custom types)

## Aggregate Roots

### What is an Aggregate?

An aggregate is a cluster of domain objects that can be treated as a single unit. An aggregate has one root entity (aggregate root) and a boundary.

**Rules:**

1. External objects can only reference the aggregate root
2. Aggregate root enforces all invariants
3. Aggregates are consistency boundaries
4. Aggregates are persisted together

### Order Aggregate Example

```python
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime
from uuid import uuid4

@dataclass
class Order:
    """Order aggregate root - enforces all business rules."""

    id: ID = field(default_factory=lambda: str(uuid4()))
    customer_id: str = ""
    items: list['OrderItem'] = field(default_factory=list)
    status: str = "draft"
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def total(self) -> Decimal:
        """Calculate total from items."""
        return sum(item.total for item in self.items)

    def add_item(self, product_id: str, quantity: int, price: Decimal):
        """Add item to order - enforces business rules."""
        if self.status != "draft":
            raise ValueError("Cannot modify non-draft order")

        if quantity <= 0:
            raise ValueError("Quantity must be positive")

        # Check if product already in order
        for item in self.items:
            if item.product_id == product_id:
                item.quantity += quantity
                item.total = item.price * item.quantity
                self.updated_at = datetime.utcnow()
                return

        # Add new item
        item = OrderItem(
            id=str(uuid4()),
            order_id=self.id,
            product_id=product_id,
            quantity=quantity,
            price=price,
            total=price * quantity
        )
        self.items.append(item)
        self.updated_at = datetime.utcnow()

    def remove_item(self, product_id: str):
        """Remove item from order."""
        if self.status != "draft":
            raise ValueError("Cannot modify non-draft order")

        self.items = [item for item in self.items if item.product_id != product_id]
        self.updated_at = datetime.utcnow()

    def submit(self):
        """Submit order for processing - state transition."""
        if self.status != "draft":
            raise ValueError("Order already submitted")

        if not self.items:
            raise ValueError("Cannot submit empty order")

        if not self.customer_id:
            raise ValueError("Customer ID required")

        self.status = "submitted"
        self.updated_at = datetime.utcnow()

    def cancel(self):
        """Cancel order."""
        if self.status in ["shipped", "delivered"]:
            raise ValueError(f"Cannot cancel {self.status} order")

        self.status = "cancelled"
        self.updated_at = datetime.utcnow()

@dataclass
class OrderItem:
    """Order item - part of Order aggregate."""
    id: ID
    order_id: str
    product_id: str
    quantity: int
    price: Decimal
    total: Decimal
```

### Using Aggregates in GraphQL

```python
import fraiseql
from graphql import GraphQLResolveInfo
from fraiseql.types import ID

@fraiseql.mutation
async def create_order(info: GraphQLResolveInfo, customer_id: ID) -> Order:
    """Create new order."""
    order = Order(customer_id=customer_id)
    order_repo = get_order_repository()
    return await order_repo.save(order)

@fraiseql.mutation
async def add_order_item(
    info: GraphQLResolveInfo,
    order_id: ID,
    product_id: ID,
    quantity: int,
    price: float
) -> Order:
    """Add item to order - enforces aggregate rules."""
    order_repo = get_order_repository()

    # Get aggregate
    order = await order_repo.get_by_id(order_id)
    if not order:
        raise ValueError("Order not found")

    # Modify through aggregate root
    order.add_item(product_id, quantity, Decimal(str(price)))

    # Save aggregate
    return await order_repo.save(order)

@fraiseql.mutation
async def submit_order(info: GraphQLResolveInfo, order_id: ID) -> Order:
    """Submit order for processing."""
    order_repo = get_order_repository()

    order = await order_repo.get_by_id(order_id)
    if not order:
        raise ValueError("Order not found")

    # State transition through aggregate
    order.submit()

    return await order_repo.save(order)
```

## Context Integration

### Integration Patterns

**1. Shared Kernel**

- Common types/entities used by multiple contexts
- Example: Customer ID, Money, Address

**2. Customer/Supplier**

- One context (supplier) provides API
- Other context (customer) consumes API

**3. Conformist**

- Downstream context conforms to upstream model
- No translation layer

**4. Anti-Corruption Layer (ACL)**

- Translation layer between contexts
- Protects domain model from external changes

**5. Published Language**

- Well-defined integration schema
- GraphQL as published language

### Integration via GraphQL

```python
import fraiseql
from fraiseql.types import ID

# Orders Context exports queries
@fraiseql.query
async def get_order(info, order_id: ID) -> Order:
    """Orders context: Get order details."""
    order_repo = get_order_repository()
    return await order_repo.get_by_id(order_id)

# Billing Context consumes Orders data
@fraiseql.mutation
async def create_invoice_for_order(info, order_id: ID) -> Invoice:
    """Billing context: Create invoice from order."""
    # Fetch order data via internal call or event
    order = await get_order(info, order_id)

    invoice = Invoice(
        id=str(uuid4()),
        order_id=order.id,
        customer_id=order.customer_id,
        amount=order.total,
        status="pending",
        due_date=datetime.utcnow() + timedelta(days=30)
    )

    invoice_repo = get_invoice_repository()
    return await invoice_repo.save(invoice)
```

## Shared Kernel

Common types shared across contexts:

```python
# shared/types.py
from dataclasses import dataclass
from decimal import Decimal
from fraiseql.types import ID

@dataclass
class Money:
    """Shared money type."""
    amount: Decimal
    currency: str = "USD"

    def __add__(self, other: 'Money') -> 'Money':
        if self.currency != other.currency:
            raise ValueError("Cannot add different currencies")
        return Money(self.amount + other.amount, self.currency)

    def __mul__(self, scalar: int | float) -> 'Money':
        return Money(self.amount * Decimal(str(scalar)), self.currency)

@dataclass
class Address:
    """Shared address type."""
    street: str
    city: str
    state: str
    postal_code: str
    country: str

@dataclass
class CustomerId:
    """Shared customer identifier."""
    value: str

    def __str__(self) -> str:
        return self.value

# Usage in Orders Context
@dataclass
class Order:
    id: ID
    customer_id: CustomerId  # Shared type
    shipping_address: Address  # Shared type
    items: list['OrderItem']
    total: Money  # Shared type
    status: str

# Usage in Billing Context
@dataclass
class Invoice:
    id: ID
    customer_id: CustomerId  # Same shared type
    billing_address: Address  # Same shared type
    amount: Money  # Same shared type
    status: str
```

## Anti-Corruption Layer

Protect your domain model from external system changes:

```python
# External system has different structure
@dataclass
class ExternalProduct:
    """External catalog system product."""
    sku: str
    title: str
    unitPrice: float
    stockLevel: int

# Your domain model
@dataclass
class Product:
    """Internal product model."""
    id: ID
    name: str
    price: Money
    quantity_available: int

# Anti-Corruption Layer
class ProductACL:
    """Translates between external and internal product models."""

    @staticmethod
    def to_domain(external: ExternalProduct) -> Product:
        """Convert external product to domain product."""
        return Product(
            id=external.sku,
            name=external.title,
            price=Money(Decimal(str(external.unitPrice)), "USD"),
            quantity_available=external.stockLevel
        )

    @staticmethod
    def to_external(product: Product) -> ExternalProduct:
        """Convert domain product to external format."""
        return ExternalProduct(
            sku=product.id,
            title=product.name,
            unitPrice=float(product.price.amount),
            stockLevel=product.quantity_available
        )

# Usage
import fraiseql
from fraiseql.types import ID

@fraiseql.query
async def get_product_from_external(info, sku: str) -> Product:
    """Fetch product from external system via ACL."""
    external_product = await fetch_from_external_catalog(sku)
    return ProductACL.to_domain(external_product)
```

## Event-Driven Communication

Contexts communicate via domain events:

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from fraiseql.types import ID
import fraiseql

@dataclass
class DomainEvent:
    """Base domain event."""
    event_type: str
    aggregate_id: str
    payload: dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.utcnow)

# Orders Context: Publish event
@fraiseql.mutation
async def submit_order(info, order_id: ID) -> Order:
    """Submit order and publish event."""
    order_repo = get_order_repository()
    order = await order_repo.get_by_id(order_id)
    order.submit()
    await order_repo.save(order)

    # Publish event for other contexts
    event = DomainEvent(
        event_type="OrderSubmitted",
        aggregate_id=order.id,
        payload={
            "order_id": order.id,
            "customer_id": order.customer_id,
            "total": str(order.total),
            "items": [
                {"product_id": item.product_id, "quantity": item.quantity}
                for item in order.items
            ]
        }
    )
    await publish_event(event)

    return order

# Billing Context: Subscribe to event
async def handle_order_submitted(event: DomainEvent):
    """Handle OrderSubmitted event from Orders context."""
    if event.event_type != "OrderSubmitted":
        return

    # Create invoice
    invoice = Invoice(
        id=str(uuid4()),
        order_id=event.payload["order_id"],
        customer_id=event.payload["customer_id"],
        amount=Decimal(event.payload["total"]),
        status="pending"
    )

    invoice_repo = get_invoice_repository()
    await invoice_repo.save(invoice)
```

## Next Steps

- [Event Sourcing](event-sourcing.md) - Event-driven architecture patterns
- [Multi-Tenancy](multi-tenancy.md) - Tenant isolation in bounded contexts
- [Performance](../performance/index.md) - Context-specific optimization
