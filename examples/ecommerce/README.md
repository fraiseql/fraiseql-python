# E-Commerce Example

An e-commerce GraphQL API with FraiseQL 1.x: users, addresses, a product catalog,
carts, orders and reviews.

> **Status: work in progress** (tracked in #574). The Python schema builds, but the
> example doesn't run end to end yet:
>
> - the query resolvers in `queries.py` are placeholders that return nothing;
> - `functions.sql` and `seed_data.sql` were written for an earlier version of the
>   schema (tables `products`, `carts`, … instead of `tb_product`, `tb_cart`, …),
>   and the mutation functions return the older `{"type": …}` JSON instead of a
>   `mutation_response`;
> - `RemoveFromCart`, `ClearCart`, `CancelOrder`, `UpdateAddress` and
>   `DeleteAddress` have no SQL function yet.
>
> For a complete, running example, see [`blog_simple`](../blog_simple/) and
> [`todo_quickstart.py`](../todo_quickstart.py).

## Files

| File | What it holds |
|------|---------------|
| `models.py` | Types (`Product`, `Cart`, `Order`, …), enums, inputs, success and error types |
| `queries.py` | Root queries (placeholders) and the connection types they return |
| `mutations.py` | Class mutations: each calls the PostgreSQL function named after it |
| `app.py` | The FastAPI app (`create_fraiseql_app`), with CORS, metrics and tracing |
| `schema.sql` | Tables (`tb_*`) and the JSONB views (`v_*`) the types read from |
| `functions.sql` | The mutation functions (see the status above) |
| `seed_data.sql` | Sample data (see the status above) |

Money amounts are `decimal.Decimal`, served as the `Decimal` scalar (a string such
as `"19.99"`).

## Running it

```bash
createdb ecommerce
psql ecommerce -f schema.sql

pip install -r requirements.txt
cd .. && DATABASE_URL=postgresql://localhost/ecommerce uvicorn ecommerce.app:app --reload
```

The app is a package module (it uses relative imports), so start it from the
`examples/` directory as `ecommerce.app:app`. The GraphQL endpoint is
`http://localhost:8000/graphql`.

## How the pieces fit

- A type reads its fields from the `data` JSONB column of its view; see
  [the JSONB view pattern](../../docs/core/concepts-glossary.md).
- A class mutation such as `AddToCart` calls the SQL function `add_to_cart` with
  its input as one `jsonb`, and returns its success or error type from the
  `mutation_response` the function returns; see
  [mutations](../../docs/core/queries-and-mutations.md).
