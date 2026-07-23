---
title: E-Commerce Platform with Complex Workflows
description: Building a production e-commerce platform on FraiseQL v1 with order management, inventory tracking, and fulfillment workflows backed by PostgreSQL.
keywords: ["workflow", "ecommerce", "orders", "inventory", "fulfillment", "postgresql"]
tags: ["documentation", "patterns"]
---

# E-Commerce Platform with Complex Workflows

**Status:** Production Ready
**Complexity:** Advanced
**Audience:** E-commerce architects, backend engineers
**Reading Time:** 25-30 minutes

A blueprint for a production e-commerce platform on FraiseQL v1: order
management, inventory tracking, and fulfillment workflows. Everything is
PostgreSQL — write tables (`tb_*`), read views (`v_*`/`tv_*`), and mutation
logic in `fn_*` functions — served as a GraphQL API by a FastAPI app.

## How multi-step workflows work in FraiseQL v1

FraiseQL v1 has no saga framework and no built-in webhook/orchestration engine.
Complex workflows are assembled from three PostgreSQL building blocks:

1. **`fn_*` functions = transactional units.** Each mutation calls one
   `fn_*` function that runs in a single transaction. Validation, the write,
   inventory reservation, and status changes either all commit or all roll
   back. This is your atomic step.
2. **`status` columns = the state machine.** An order moves through
   `pending → confirmed → processing → shipped → delivered` (or `cancelled`)
   by updating a `status` column *inside* an `fn_*` function. A `BEFORE UPDATE`
   trigger enforces legal transitions.
3. **A transactional outbox = cross-system steps.** Anything that touches an
   external system (charge a card, send an email, notify a carrier) is written
   as a row into an outbox table *in the same transaction* as the order change.
   A background worker you run polls the outbox, performs the side effect, and
   marks the row done. This gives you exactly-once-ish delivery without a
   distributed saga coordinator: if the transaction rolls back, the outbox row
   never exists; if it commits, the worker will eventually drain it.

The result is a reliable, observable workflow built entirely from PostgreSQL
transactions plus one worker process — no external orchestration layer.

---

## Schema Design

FraiseQL v1 separates the **write side** (`tb_*` normalized tables, the source
of truth) from the **read side** (`v_*` / `tv_*` views that build a `data`
JSONB payload for GraphQL). Mutations write through `fn_*` functions; queries
read the views.

### Products & Inventory (write tables)

```sql
CREATE TABLE tb_product (
  pk_product       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,  -- internal, hidden
  id               UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),   -- public GraphQL id
  sku              VARCHAR(50) UNIQUE NOT NULL,
  name             VARCHAR(255) NOT NULL,
  description      TEXT,
  fk_category      BIGINT NOT NULL REFERENCES tb_category(pk_category),
  brand            VARCHAR(100),
  price            DECIMAL(12, 2) NOT NULL,
  cost             DECIMAL(12, 2),                 -- for margin calculation
  status           VARCHAR(50) NOT NULL DEFAULT 'draft',  -- active, draft, discontinued
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Product variants (sizes, colors, etc.)
CREATE TABLE tb_product_variant (
  pk_product_variant BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id                 UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  fk_product         BIGINT NOT NULL REFERENCES tb_product(pk_product) ON DELETE CASCADE,
  sku                VARCHAR(50) UNIQUE NOT NULL,
  name               VARCHAR(255),                 -- e.g. "Red - Size M"
  price_modifier     DECIMAL(10, 2) DEFAULT 0,     -- +$5 for premium variant
  weight             DECIMAL(8, 3),
  dimensions         JSONB,                        -- {"width": 10, "height": 20, "depth": 5}
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_variant_product ON tb_product_variant (fk_product);

-- Inventory tracking (stock levels)
CREATE TABLE tb_inventory (
  pk_inventory        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id                  UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  fk_product_variant  BIGINT NOT NULL REFERENCES tb_product_variant(pk_product_variant),
  fk_warehouse        BIGINT NOT NULL REFERENCES tb_warehouse(pk_warehouse),
  quantity_on_hand    INT NOT NULL DEFAULT 0,
  quantity_reserved   INT NOT NULL DEFAULT 0,
  quantity_available  INT GENERATED ALWAYS AS (quantity_on_hand - quantity_reserved) STORED,
  reorder_point       INT,
  reorder_quantity    INT,
  last_stock_check    TIMESTAMPTZ,
  UNIQUE (fk_product_variant, fk_warehouse)
);
CREATE INDEX idx_inventory_warehouse  ON tb_inventory (fk_warehouse);
CREATE INDEX idx_inventory_available  ON tb_inventory (quantity_available);

-- Stock movements (audit trail)
CREATE TABLE tb_stock_movement (
  pk_stock_movement   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id                  UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  fk_product_variant  BIGINT NOT NULL REFERENCES tb_product_variant(pk_product_variant),
  fk_warehouse        BIGINT NOT NULL REFERENCES tb_warehouse(pk_warehouse),
  movement_type       VARCHAR(50) NOT NULL,        -- purchase, return, adjustment, damage
  quantity            INT NOT NULL,
  reference           VARCHAR(50),                 -- order id, return id
  notes               TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_movement_variant ON tb_stock_movement (fk_product_variant);
CREATE INDEX idx_movement_type    ON tb_stock_movement (movement_type);
```

### Orders & Fulfillment (write tables)

```sql
-- Orders (customer purchases)
CREATE TABLE tb_order (
  pk_order            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id                  UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  order_number        VARCHAR(20) UNIQUE NOT NULL,  -- public facing
  fk_customer         BIGINT NOT NULL REFERENCES tb_customer(pk_customer),
  status              VARCHAR(50) NOT NULL DEFAULT 'pending',
                      -- pending, confirmed, processing, shipped, delivered, cancelled
  subtotal            DECIMAL(12, 2),
  tax                 DECIMAL(10, 2),
  shipping_cost       DECIMAL(10, 2),
  discount_amount     DECIMAL(10, 2),
  total               DECIMAL(12, 2) NOT NULL,
  currency            VARCHAR(3) NOT NULL,          -- USD, EUR, etc.
  payment_status      VARCHAR(50) NOT NULL DEFAULT 'pending',  -- pending, completed, failed, refunded
  fk_billing_address  BIGINT NOT NULL REFERENCES tb_address(pk_address),
  fk_shipping_address BIGINT NOT NULL REFERENCES tb_address(pk_address),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  shipped_at          TIMESTAMPTZ,
  delivered_at        TIMESTAMPTZ,
  cancelled_at        TIMESTAMPTZ
);
CREATE INDEX idx_order_customer ON tb_order (fk_customer);
CREATE INDEX idx_order_status   ON tb_order (status);
CREATE INDEX idx_order_payment  ON tb_order (payment_status);
CREATE INDEX idx_order_created  ON tb_order (created_at);

-- Order line items
CREATE TABLE tb_order_item (
  pk_order_item       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id                  UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  fk_order            BIGINT NOT NULL REFERENCES tb_order(pk_order) ON DELETE CASCADE,
  fk_product_variant  BIGINT NOT NULL REFERENCES tb_product_variant(pk_product_variant),
  quantity            INT NOT NULL,
  unit_price          DECIMAL(12, 2) NOT NULL,
  discount_amount     DECIMAL(10, 2) DEFAULT 0,
  total               DECIMAL(12, 2) NOT NULL
);
CREATE INDEX idx_order_item_order ON tb_order_item (fk_order);

-- Fulfillment operations
CREATE TABLE tb_fulfillment (
  pk_fulfillment      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id                  UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  fk_order            BIGINT NOT NULL REFERENCES tb_order(pk_order),
  status              VARCHAR(50) NOT NULL DEFAULT 'pending',  -- pending, shipped, delivered, cancelled
  tracking_number     VARCHAR(100),
  carrier             VARCHAR(50),                 -- FedEx, UPS, USPS
  estimated_delivery  DATE,
  actual_delivery     TIMESTAMPTZ,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_fulfillment_order  ON tb_fulfillment (fk_order);
CREATE INDEX idx_fulfillment_status ON tb_fulfillment (status);

-- Fulfillment line items
CREATE TABLE tb_fulfillment_item (
  pk_fulfillment_item BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id                  UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  fk_fulfillment      BIGINT NOT NULL REFERENCES tb_fulfillment(pk_fulfillment) ON DELETE CASCADE,
  fk_order_item       BIGINT NOT NULL REFERENCES tb_order_item(pk_order_item),
  quantity            INT NOT NULL
);
CREATE INDEX idx_fulfillment_item_fulfillment ON tb_fulfillment_item (fk_fulfillment);

-- Returns & Refunds
CREATE TABLE tb_return (
  pk_return           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id                  UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  fk_order            BIGINT NOT NULL REFERENCES tb_order(pk_order),
  status              VARCHAR(50) NOT NULL DEFAULT 'pending',  -- pending, approved, shipped, received, refunded
  reason              VARCHAR(255),
  refund_amount       DECIMAL(12, 2),
  refund_status       VARCHAR(50) NOT NULL DEFAULT 'pending',  -- pending, completed, failed
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  refunded_at         TIMESTAMPTZ
);
CREATE INDEX idx_return_order  ON tb_return (fk_order);
CREATE INDEX idx_return_status ON tb_return (status);

-- Return line items
CREATE TABLE tb_return_item (
  pk_return_item      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id                  UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  fk_return           BIGINT NOT NULL REFERENCES tb_return(pk_return) ON DELETE CASCADE,
  fk_order_item       BIGINT NOT NULL REFERENCES tb_order_item(pk_order_item),
  quantity            INT NOT NULL,
  condition           VARCHAR(50)                  -- unopened, opened, defective
);
CREATE INDEX idx_return_item_return ON tb_return_item (fk_return);
```

### Payments & Discounts (write tables)

```sql
CREATE TABLE tb_payment (
  pk_payment      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id              UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  fk_order        BIGINT NOT NULL REFERENCES tb_order(pk_order),
  amount          DECIMAL(12, 2) NOT NULL,
  status          VARCHAR(50) NOT NULL DEFAULT 'pending',  -- pending, completed, failed, refunded
  payment_method  VARCHAR(50),                     -- credit_card, paypal, stripe
  transaction_id  VARCHAR(100),
  error_message   TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_payment_order  ON tb_payment (fk_order);
CREATE INDEX idx_payment_status ON tb_payment (status);

CREATE TABLE tb_discount (
  pk_discount       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id                UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  code              VARCHAR(50) UNIQUE NOT NULL,
  type              VARCHAR(50) NOT NULL,          -- percentage, fixed_amount
  value             DECIMAL(10, 2) NOT NULL,
  max_uses          INT,
  current_uses      INT DEFAULT 0,
  min_order_amount  DECIMAL(10, 2),
  valid_from        DATE,
  valid_until       DATE,
  is_active         BOOLEAN DEFAULT TRUE
);
CREATE INDEX idx_discount_code   ON tb_discount (code);
CREATE INDEX idx_discount_active ON tb_discount (is_active);

CREATE TABLE tb_order_discount (
  pk_order_discount BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  fk_order          BIGINT NOT NULL REFERENCES tb_order(pk_order),
  fk_discount       BIGINT NOT NULL REFERENCES tb_discount(pk_discount),
  discount_amount   DECIMAL(10, 2),
  UNIQUE (fk_order, fk_discount)
);
```

### The transactional outbox (cross-system steps)

Cross-system side effects are recorded here in the same transaction as the
business write, then drained by your worker.

```sql
CREATE TABLE tb_outbox (
  pk_outbox     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id            UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  topic         VARCHAR(100) NOT NULL,             -- charge_payment, send_email, notify_carrier
  payload       JSONB NOT NULL,
  status        VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending, processing, done, failed
  attempts      INT NOT NULL DEFAULT 0,
  available_at  TIMESTAMPTZ NOT NULL DEFAULT now(),  -- for retry backoff
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  processed_at  TIMESTAMPTZ
);
CREATE INDEX idx_outbox_pending ON tb_outbox (available_at) WHERE status = 'pending';
```

---

## Read views

GraphQL reads come from `v_*` views (or `tv_*` projection tables for heavy
nested reads). Each view exposes the public `id` (UUID) and a `data` JSONB
column built with `jsonb_build_object(...)`. Internal `pk_*` / `fk_*` columns
never appear in `data`.

```sql
-- Product read view: id + data JSONB shaped for GraphQL
CREATE VIEW v_product AS
SELECT
  p.id,                                            -- public id for WHERE id = $1
  jsonb_build_object(
    'id',           p.id,
    'sku',          p.sku,
    'name',         p.name,
    'description',  p.description,
    'price',        p.price,
    'status',       p.status,
    'inStock',      COALESCE(SUM(inv.quantity_available) > 0, false),
    'rating',       COALESCE(AVG(r.rating), 0),
    'variants', (
      SELECT jsonb_agg(jsonb_build_object(
        'id',                pv.id,
        'name',              pv.name,
        'sku',               pv.sku,
        'price',             p.price + COALESCE(pv.price_modifier, 0),
        'weight',            pv.weight,
        'availableQuantity', COALESCE(vinv.quantity_available, 0)
      ))
      FROM tb_product_variant pv
      LEFT JOIN tb_inventory vinv ON vinv.fk_product_variant = pv.pk_product_variant
      WHERE pv.fk_product = p.pk_product
    )
  ) AS data
FROM tb_product p
LEFT JOIN tb_product_variant pv2 ON pv2.fk_product = p.pk_product
LEFT JOIN tb_inventory inv       ON inv.fk_product_variant = pv2.pk_product_variant
LEFT JOIN tb_review r            ON r.fk_product = p.pk_product
GROUP BY p.pk_product, p.id, p.sku, p.name, p.description, p.price, p.status;

-- Order read view
CREATE VIEW v_order AS
SELECT
  o.id,
  o.fk_customer,                                   -- kept for filtering / RLS, not in data
  jsonb_build_object(
    'id',             o.id,
    'orderNumber',    o.order_number,
    'status',         o.status,
    'subtotal',       o.subtotal,
    'tax',            o.tax,
    'shippingCost',   o.shipping_cost,
    'total',          o.total,
    'currency',       o.currency,
    'paymentStatus',  o.payment_status,
    'createdAt',      o.created_at,
    'shippedAt',      o.shipped_at,
    'items', (
      SELECT jsonb_agg(jsonb_build_object(
        'id',        oi.id,
        'quantity',  oi.quantity,
        'unitPrice', oi.unit_price,
        'total',     oi.total
      ))
      FROM tb_order_item oi
      WHERE oi.fk_order = o.pk_order
    )
  ) AS data
FROM tb_order o;
```

For order detail pages that fan out into items, fulfillments, and returns, a
`tv_order` projection table (a real table holding pre-composed JSONB, refreshed
by your `fn_*` functions or triggers) keeps heavy nested reads fast.

---

## FraiseQL types, queries, and mutations

Define GraphQL types over the read views, queries over the views, and mutations
over the `fn_*` functions. Mutations return a `success | error` union.

```python
# ecommerce_schema.py
from datetime import date, datetime
from decimal import Decimal

import fraiseql
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.types import ID

from .authz import customer_authorizer, admin_authorizer


@fraiseql.type(sql_source="v_product", jsonb_column="data")
class Product:
    id: ID
    sku: str
    name: str
    price: Decimal
    rating: Decimal           # average rating, computed in the view
    in_stock: bool
    variants: list["ProductVariant"]


@fraiseql.type(sql_source="v_product_variant", jsonb_column="data")
class ProductVariant:
    id: ID
    name: str
    sku: str
    price: Decimal
    weight: Decimal | None
    available_quantity: int


@fraiseql.type(sql_source="v_order", jsonb_column="data")
class Order:
    id: ID
    order_number: str
    status: str
    items: list["OrderItem"]
    subtotal: Decimal
    tax: Decimal
    shipping_cost: Decimal
    total: Decimal
    payment_status: str
    created_at: datetime
    shipped_at: datetime | None


@fraiseql.type(sql_source="v_order_item", jsonb_column="data")
class OrderItem:
    id: ID
    quantity: int
    unit_price: Decimal
    total: Decimal


@fraiseql.type(sql_source="v_fulfillment", jsonb_column="data")
class Fulfillment:
    id: ID
    status: str
    tracking_number: str | None
    carrier: str | None
    estimated_delivery: date | None


@fraiseql.type(sql_source="v_return", jsonb_column="data")
class Return:
    id: ID
    status: str
    refund_amount: Decimal
    refund_status: str
    reason: str
```

### Inputs and result unions

```python
@fraiseql.input
class OrderLineInput:
    variant_id: ID
    quantity: int


@fraiseql.input
class CreateOrderInput:
    lines: list[OrderLineInput]
    shipping_address_id: ID
    discount_code: str | None = None


@fraiseql.success
class CreateOrderSuccess:
    order: Order              # @success auto-injects status/message/id


@fraiseql.error
class CreateOrderError:
    message: str
    code: str = "ORDER_FAILED"
```

### Queries

Authorization is applied per operation with an `Authorizer` passed to the
decorator — there is no `@authorize` decorator in v1. Row scoping (a customer
sees only their own orders) is enforced by PostgreSQL Row-Level Security on the
underlying tables, driven by the session GUCs FraiseQL sets from
`info.context`. See [Multi-Tenant SaaS](./saas-multi-tenant.md) for the RLS
pattern.

```python
@fraiseql.query
async def product(info, id: ID) -> Product | None:
    db = info.context["db"]
    return await db.find_one("v_product", id=id)


@fraiseql.query
async def search_products(
    info,
    query: str,
    category: str | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    limit: int = 50,
) -> list[Product]:
    db = info.context["db"]
    return await db.find("v_product", search=query, limit=limit)


@fraiseql.query(authorizer=customer_authorizer)
async def my_orders(info, limit: int = 20) -> list[Order]:
    """Current user's orders (scoped to the caller by RLS)."""
    db = info.context["db"]
    return await db.find("v_order", limit=limit)


@fraiseql.query(authorizer=admin_authorizer)
async def orders(info, status: str | None = None, limit: int = 50) -> list[Order]:
    db = info.context["db"]
    filters = {"status": status} if status else {}
    return await db.find("v_order", limit=limit, **filters)
```

### Mutations

Each mutation calls one `fn_*` function. The function runs in a transaction:
it validates input, performs the write, reserves inventory, updates the
`status` column, and (for cross-system steps) inserts outbox rows — all
atomically. It returns a JSONB object with a `success` flag.

```python
@fraiseql.mutation(authorizer=customer_authorizer)
async def create_order(
    info, input: CreateOrderInput
) -> CreateOrderSuccess | CreateOrderError:
    db = info.context["db"]
    result = await db.execute_function(
        "fn_create_order",
        {
            "lines": [{"variant_id": str(l.variant_id), "quantity": l.quantity} for l in input.lines],
            "shipping_address_id": str(input.shipping_address_id),
            "discount_code": input.discount_code,
        },
    )
    if not result.get("success"):
        return CreateOrderError(
            message=result.get("message", "Order creation failed"),
            code=result.get("code", "ORDER_FAILED"),
        )
    return CreateOrderSuccess(order=Order(**result["order"]))


@fraiseql.mutation(authorizer=customer_authorizer)
async def cancel_order(info, order_id: ID) -> CreateOrderSuccess | CreateOrderError:
    db = info.context["db"]
    result = await db.execute_function("fn_cancel_order", {"order_id": str(order_id)})
    if not result.get("success"):
        return CreateOrderError(message=result.get("message", "Cancellation failed"))
    return CreateOrderSuccess(order=Order(**result["order"]))


app = create_fraiseql_app(
    database_url="postgresql://localhost/shop",
    types=[Product, ProductVariant, Order, OrderItem, Fulfillment, Return],
    queries=[product, search_products, my_orders, orders],
    mutations=[create_order, cancel_order],
    production=False,   # False enables the GraphQL playground
)
```

Run it with `uvicorn ecommerce_schema:app`.

---

## Order Lifecycle

### State Machine

The order `status` column is the state machine. Transitions happen only inside
`fn_*` functions, and a trigger rejects illegal jumps.

```text
pending  ──► confirmed ──► processing ──► shipped ──► delivered
   │            │              │             │
   └────────────┴──────────────┴─────────────┘
                      ▼
                  cancelled
```

| From         | Allowed next states          |
|--------------|------------------------------|
| `pending`    | `confirmed`, `cancelled`     |
| `confirmed`  | `processing`, `cancelled`    |
| `processing` | `shipped`, `cancelled`       |
| `shipped`    | `delivered`, `cancelled`     |
| `delivered`  | *(terminal)*                 |
| `cancelled`  | *(terminal)*                 |

### State transition guard

```sql
CREATE OR REPLACE FUNCTION fn_validate_order_transition()
RETURNS TRIGGER AS $$
BEGIN
  CASE
    WHEN OLD.status = 'pending'    AND NEW.status NOT IN ('confirmed', 'cancelled') THEN
      RAISE EXCEPTION 'Invalid transition from pending to %', NEW.status;
    WHEN OLD.status = 'confirmed'  AND NEW.status NOT IN ('processing', 'cancelled') THEN
      RAISE EXCEPTION 'Invalid transition from confirmed to %', NEW.status;
    WHEN OLD.status = 'processing' AND NEW.status NOT IN ('shipped', 'cancelled') THEN
      RAISE EXCEPTION 'Invalid transition from processing to %', NEW.status;
    WHEN OLD.status = 'shipped'    AND NEW.status NOT IN ('delivered', 'cancelled') THEN
      RAISE EXCEPTION 'Invalid transition from shipped to %', NEW.status;
    WHEN OLD.status IN ('delivered', 'cancelled') THEN
      RAISE EXCEPTION 'Cannot change a delivered or cancelled order';
    ELSE
      NULL;  -- transition allowed
  END CASE;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER order_status_validation
BEFORE UPDATE ON tb_order
FOR EACH ROW
WHEN (OLD.status IS DISTINCT FROM NEW.status)
EXECUTE FUNCTION fn_validate_order_transition();
```

### The `fn_create_order` mutation function

This is the transactional unit behind the `create_order` mutation: it creates
the order, reserves inventory, sets the initial status, and enqueues the
payment side effect — all in one transaction.

```sql
CREATE OR REPLACE FUNCTION fn_create_order(input JSONB)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
  v_order_pk    BIGINT;
  v_order_id    UUID;
  v_line        JSONB;
  v_variant_pk  BIGINT;
  v_total       DECIMAL(12, 2) := 0;
BEGIN
  -- 1. Create the order shell (status defaults to 'pending')
  INSERT INTO tb_order (order_number, fk_customer, total, currency,
                        fk_billing_address, fk_shipping_address)
  VALUES (
    'ORD-' || to_char(now(), 'YYYYMMDD') || '-' || nextval('order_number_seq'),
    current_setting('app.customer_pk')::BIGINT,
    0, 'USD',
    (input->>'shipping_address_id')::UUID::TEXT::BIGINT,  -- resolve via lookup in practice
    (input->>'shipping_address_id')::UUID::TEXT::BIGINT
  )
  RETURNING pk_order, id INTO v_order_pk, v_order_id;

  -- 2. Add line items and reserve inventory atomically
  FOR v_line IN SELECT * FROM jsonb_array_elements(input->'lines')
  LOOP
    SELECT pk_product_variant INTO v_variant_pk
    FROM tb_product_variant
    WHERE id = (v_line->>'variant_id')::UUID;

    UPDATE tb_inventory
    SET quantity_reserved = quantity_reserved + (v_line->>'quantity')::INT
    WHERE fk_product_variant = v_variant_pk
      AND quantity_available >= (v_line->>'quantity')::INT;

    IF NOT FOUND THEN
      RAISE EXCEPTION 'INSUFFICIENT_STOCK:%', v_line->>'variant_id';
    END IF;

    INSERT INTO tb_order_item (fk_order, fk_product_variant, quantity, unit_price, total)
    SELECT v_order_pk, v_variant_pk, (v_line->>'quantity')::INT, p.price,
           p.price * (v_line->>'quantity')::INT
    FROM tb_product_variant pv
    JOIN tb_product p ON p.pk_product = pv.fk_product
    WHERE pv.pk_product_variant = v_variant_pk;
  END LOOP;

  -- 3. Recompute total
  SELECT COALESCE(SUM(total), 0) INTO v_total
  FROM tb_order_item WHERE fk_order = v_order_pk;
  UPDATE tb_order SET total = v_total, subtotal = v_total WHERE pk_order = v_order_pk;

  -- 4. Enqueue the cross-system payment step in the SAME transaction
  INSERT INTO tb_outbox (topic, payload)
  VALUES ('charge_payment',
          jsonb_build_object('order_id', v_order_id, 'amount', v_total));

  -- Everything above commits together, or nothing does.
  RETURN jsonb_build_object(
    'success', true,
    'order', jsonb_build_object('id', v_order_id, 'status', 'pending', 'total', v_total)
  );
EXCEPTION
  WHEN OTHERS THEN
    RETURN jsonb_build_object(
      'success', false,
      'message', SQLERRM,
      'code', split_part(SQLERRM, ':', 1)
    );
END;
$$;
```

---

## Inventory Management

Inventory is reserved inside `fn_create_order` (above) and released inside the
cancellation function. Keeping the reserve/release in the same transaction as
the status change is what prevents overselling — there is no separate
coordinator to keep in sync.

### Release inventory on cancellation

```sql
CREATE OR REPLACE FUNCTION fn_cancel_order(input JSONB)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
  v_order_pk BIGINT;
  v_order_id UUID := (input->>'order_id')::UUID;
BEGIN
  SELECT pk_order INTO v_order_pk FROM tb_order WHERE id = v_order_id;
  IF v_order_pk IS NULL THEN
    RETURN jsonb_build_object('success', false, 'message', 'Order not found');
  END IF;

  -- Release reserved stock for every line on the order
  UPDATE tb_inventory inv
  SET quantity_reserved = quantity_reserved - oi.quantity
  FROM tb_order_item oi
  WHERE inv.fk_product_variant = oi.fk_product_variant
    AND oi.fk_order = v_order_pk;

  -- Flip status (the BEFORE UPDATE trigger validates the transition)
  UPDATE tb_order
  SET status = 'cancelled', cancelled_at = now()
  WHERE pk_order = v_order_pk;

  -- Cross-system step: notify the customer
  INSERT INTO tb_outbox (topic, payload)
  VALUES ('send_email',
          jsonb_build_object('template', 'order_cancelled', 'order_id', v_order_id));

  RETURN jsonb_build_object(
    'success', true,
    'order', jsonb_build_object('id', v_order_id, 'status', 'cancelled')
  );
EXCEPTION
  WHEN OTHERS THEN
    RETURN jsonb_build_object('success', false, 'message', SQLERRM);
END;
$$;
```

---

## Cross-system steps: the outbox worker

The mutation transaction only ever touches PostgreSQL. External effects
(charging a card via Stripe, sending email, notifying a carrier) are recorded
in `tb_outbox` and performed *afterward* by a worker you run alongside the
FastAPI app. This is the v1 substitute for a saga/webhook engine: there is no
built-in orchestration, but the outbox gives you the same reliability
guarantees with plain SQL.

```python
# worker.py — run as a separate process: python -m worker
import asyncio
import json

import psycopg

import payments  # your Stripe/PayPal client
import mailer    # your email client


async def drain_outbox(conn: psycopg.AsyncConnection) -> None:
    # Claim one pending row with FOR UPDATE SKIP LOCKED so multiple
    # workers never grab the same job.
    async with conn.transaction():
        row = await (await conn.execute(
            """
            SELECT pk_outbox, topic, payload
            FROM tb_outbox
            WHERE status = 'pending' AND available_at <= now()
            ORDER BY available_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
        )).fetchone()
        if row is None:
            return

        pk, topic, payload = row
        try:
            if topic == "charge_payment":
                await payments.charge(payload["order_id"], payload["amount"])
                # Confirm the order via its own fn_ function (its own transaction)
                await conn.execute(
                    "SELECT fn_mark_order_paid(%s)", (json.dumps(payload),)
                )
            elif topic == "send_email":
                await mailer.send(payload)
            elif topic == "notify_carrier":
                await payments.notify_carrier(payload)  # illustrative

            await conn.execute(
                "UPDATE tb_outbox SET status = 'done', processed_at = now() WHERE pk_outbox = %s",
                (pk,),
            )
        except Exception as exc:  # retry with backoff
            await conn.execute(
                """
                UPDATE tb_outbox
                SET attempts = attempts + 1,
                    available_at = now() + (attempts + 1) * interval '30 seconds',
                    status = CASE WHEN attempts + 1 >= 5 THEN 'failed' ELSE 'pending' END,
                    error_message = %s
                WHERE pk_outbox = %s
                """,
                (str(exc), pk),
            )


async def main() -> None:
    async with await psycopg.AsyncConnection.connect("postgresql://localhost/shop") as conn:
        while True:
            await drain_outbox(conn)
            await asyncio.sleep(0.5)


if __name__ == "__main__":
    asyncio.run(main())
```

Key properties:

- **Atomicity** — the outbox row and the order write share one transaction, so
  you never charge a card for an order that rolled back.
- **At-least-once delivery** — the worker retries with backoff; downstream
  effects (payment confirmation via `fn_mark_order_paid`) are idempotent.
- **Back-pressure & ordering** — `FOR UPDATE SKIP LOCKED` lets you scale to
  several workers without double-processing.

---

## Reporting & Analytics

Sales reporting is plain PostgreSQL aggregation inside a view, served as a
GraphQL type. FraiseQL v1 supports runtime auto-aggregation (COUNT, SUM, AVG,
MIN, MAX, STDDEV, VARIANCE) over view-backed types, and you can also pre-shape
metrics directly in the view with `DATE_TRUNC` time bucketing.

```sql
CREATE VIEW v_order_metrics AS
SELECT
  DATE_TRUNC('day', o.created_at)::DATE AS id,    -- bucket key, used as the view id
  jsonb_build_object(
    'day',               DATE_TRUNC('day', o.created_at)::DATE,
    'totalRevenue',      SUM(o.total) FILTER (WHERE o.payment_status = 'completed'),
    'orderCount',        COUNT(*),
    'averageOrderValue', AVG(o.total),
    'cancelledCount',    COUNT(*) FILTER (WHERE o.status = 'cancelled')
  ) AS data
FROM tb_order o
GROUP BY DATE_TRUNC('day', o.created_at);
```

```python
@fraiseql.type(sql_source="v_order_metrics", jsonb_column="data")
class OrderMetrics:
    day: date
    total_revenue: Decimal
    order_count: int
    average_order_value: Decimal
    cancelled_count: int


@fraiseql.query(authorizer=admin_authorizer)
async def order_metrics(info, start_date: date, end_date: date) -> list[OrderMetrics]:
    db = info.context["db"]
    return await db.find("v_order_metrics", day__gte=start_date, day__lte=end_date)
```

A client query:

```graphql
query OrderMetrics($start: Date!, $end: Date!) {
  orderMetrics(startDate: $start, endDate: $end) {
    day
    totalRevenue
    orderCount
    averageOrderValue
  }
}
```

For dedicated reporting workloads, materialize the metrics into a `tv_*`
projection table refreshed on a schedule instead of computing the aggregate on
every request.

---

## Testing Order Workflows

Because all the workflow logic lives in `fn_*` functions, the highest-value
tests are integration tests that run the mutation against a real PostgreSQL
database and assert on the resulting state. FraiseQL v1 uses
`pytest` + `pytest-asyncio`.

```python
import pytest


@pytest.mark.asyncio
async def test_create_order_reserves_inventory(db, seed_variant):
    """Creating an order reserves stock atomically."""
    variant_id = await seed_variant(quantity_on_hand=100)

    result = await db.execute_function(
        "fn_create_order",
        {"lines": [{"variant_id": str(variant_id), "quantity": 10}],
         "shipping_address_id": "addr-uuid"},
    )

    assert result["success"] is True
    inv = await db.find_one("v_inventory", variant_id=variant_id)
    assert inv["quantity_reserved"] == 10
    assert inv["quantity_available"] == 90


@pytest.mark.asyncio
async def test_create_order_prevents_overselling(db, seed_variant):
    """Ordering more than is available fails and reserves nothing."""
    variant_id = await seed_variant(quantity_on_hand=5)

    result = await db.execute_function(
        "fn_create_order",
        {"lines": [{"variant_id": str(variant_id), "quantity": 10}],
         "shipping_address_id": "addr-uuid"},
    )

    assert result["success"] is False
    assert "INSUFFICIENT_STOCK" in result["message"]
    inv = await db.find_one("v_inventory", variant_id=variant_id)
    assert inv["quantity_reserved"] == 0   # transaction rolled back


@pytest.mark.asyncio
async def test_cancel_order_releases_inventory(db, seeded_order):
    """Cancelling an order releases its reserved stock."""
    order_id, variant_id = seeded_order
    before = await db.find_one("v_inventory", variant_id=variant_id)

    result = await db.execute_function("fn_cancel_order", {"order_id": str(order_id)})

    assert result["success"] is True
    after = await db.find_one("v_inventory", variant_id=variant_id)
    assert after["quantity_reserved"] == before["quantity_reserved"] - 10


@pytest.mark.asyncio
async def test_outbox_row_enqueued_on_order(db, seed_variant):
    """The payment side effect is recorded in the outbox, not executed inline."""
    variant_id = await seed_variant(quantity_on_hand=50)

    result = await db.execute_function(
        "fn_create_order",
        {"lines": [{"variant_id": str(variant_id), "quantity": 1}],
         "shipping_address_id": "addr-uuid"},
    )

    rows = await db.find("v_outbox", topic="charge_payment", status="pending")
    assert any(r["payload"]["order_id"] == result["order"]["id"] for r in rows)
```

---

## See Also

**Related Patterns:**

- [Patterns overview](./README.md) - Index of application blueprints
- [Multi-Tenant SaaS](./saas-multi-tenant.md) - RLS-based tenant and role isolation
- [Analytics Platform](./analytics-olap-platform.md) - Sales reporting and OLAP

**Guides:**

- [Integration Patterns](../architecture/integration/integration-patterns.md) - FastAPI integration, FDW, `fn_*` functions
- [Error Handling & Validation](../foundation/10-error-handling-validation.md) - Success/error unions and mutation results
