# Changelog

All notable changes to FraiseQL are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **A `Decimal` scalar for `decimal.Decimal`** (#575). A `decimal.Decimal`
  field failed the schema build (`Unsupported output type`) as an output field,
  an input field or an argument, and so did every where input of a type with a
  `Decimal` field (`DecimalFilter`). It now maps to the `Decimal` scalar,
  serialized as a string (`"12.30"`, every digit kept) and parsed to
  `decimal.Decimal` from a string, an int or a number literal.

  A `Decimal` input field reaches your SQL function as a JSON string; read it
  with `(input->>'price')::numeric`. In HTTP mode the Rust pipeline parses JSONB
  numbers as 64-bit floats, so emit the column as text in your view
  (`'price', price::text`) to keep every digit; a JSONB number keeps about 17
  significant digits and reaches the client as a number.

### Fixed

- **`SchemaRegistry.clear()` now clears registered scalars** (#589). It left
  them in place, so a schema built after `clear()` (or after
  `fraiseql.testing.clear_fraiseql_state()`) still held every scalar registered
  before it, and a later type with the same name, such as an enum called `Color`,
  failed with `Schema must contain uniquely named types`. Types registered after
  `clear()` register the scalars they use again, as they do on first
  registration. A scalar you registered by hand with `register_scalar()` must be
  registered again after `clear()`.
### Added

- **`requires_any_role` and `requires_any_permission` are exported from
  `fraiseql.auth` and `fraiseql`** (#577). They were importable only from
  `fraiseql.auth.decorators`, so the documented
  `from fraiseql.auth import requires_any_role` failed with `ImportError`.
  `requires_role` and `requires_permission` take one role or permission; use
  these for "any of":

  ```python
  from fraiseql.auth import requires_any_role

  @requires_any_role("owner", "admin")
  async def delete_project(info, project_id: UUID) -> Project: ...
  ```

### Fixed

- **The type stub declared an `optional=` keyword on `requires_auth`,
  `requires_role` and `requires_permission`** that they don't accept (#577).
  `fraiseql/__init__.pyi` now matches the runtime signatures, so a type checker
  flags `requires_role("admin", optional=True)`, which fails at runtime.
### Changed

- **The schema build rejects class mutations with members fraiseql doesn't
  read** (#576, #587). A class mutation reads only `input:`, `success:`,
  `error:` and `prepare_input`. Anything else was ignored without a word:
  `failure:` or `noop:` left the error type unreachable (the field returned the
  success type alone), and an `async def resolve()` method never ran. The build
  now raises one `TypeError` listing every faulty mutation:

  ```text
  Invalid class mutations:
  - Mutation CreateThing has `failure`, which fraiseql doesn't read: a class mutation reads only `input:`, `success:`, `error:` and `prepare_input`. For the error type, use `error:`.
  ```

  Members inherited from base classes and mixins count, and names starting
  with `_` (private helpers) are allowed. To upgrade: rename `failure:` (or
  `errors:`) to `error:`; remove `noop:` (a `noop:*` status already returns the
  error type); move the code of a `resolve()` method into a function mutation,
  `@fraiseql.mutation async def create_thing(info, input: CreateThingInput) -> CreateThingSuccess | CreateThingError`.

### Fixed

- **A class mutation without `input:` failed with an error naming neither the
  mutation nor the annotation** (#576): `Invalid type passed to
  convert_type_to_graphql_input: <class 'NoneType'>`. The schema build now says
  `Mutation ClearCart has no `input:` annotation` and points to function
  mutations for mutations without arguments. A class with neither `success:` nor
  `error:` gets a similar message instead of `Unsupported output type`.
- **Number filters on JSONB fields compared text** (#575). A filter such as
  `where: {quantity: {gt: 9}}` on a field of the JSONB data compared
  `data->>'quantity'` with the text `'9'`: `10` didn't match (as text,
  `'10' < '9'`), and `{price: {eq: 10.5}}` missed `10.50`. A number is now
  compared as `numeric`, `(data->>'quantity')::numeric > 9`, for `eq`, `neq`,
  `gt`, `gte`, `lt`, `lte`, `in` and `nin`. If the field holds something that
  isn't a number in a row the filter reaches, PostgreSQL now raises
  `invalid input syntax for type numeric` instead of comparing text. Strings and
  booleans are compared as before.
### Changed

- **A mutation response holds only what the query selected, under its response
  keys** (#581, #573). In HTTP mode the response Rust builds goes to the client as
  is, and it didn't apply GraphQL selections faithfully. Now:
  - every alias is kept: on the mutation field (`m: createUser`), on fields of the
    success and error types (`msg: message`), and in the entity (`other: owner { id }`);
    one field under two aliases gets each its own sub-selection;
  - lists are filtered element by element at any depth (`tags { id }` returned
    every key of every tag);
  - with no fields selected on the success type (`{ __typename }`, or only a
    fragment on the error type), the result is `{"__typename": ...}` alone. It
    was the whole entity, every key of its JSONB included;
  - under a field typed as an interface or union, an object keeps the fields of
    the fragments on its own type, picked by its `__typename` (`... on Person
    { name } ... on Org { title }` gave a `Person` its `title` too). The view must
    emit `__typename` in the nested JSONB; without it, the fields of every
    fragment are kept, as before;
  - the error type's `code` appears only when selected; it was always written.

  Objects keep their `__typename` whether or not it is selected, as before.
  Outside HTTP mode graphql-core already applied the selection; it now receives
  the same filtered data.

  `fraiseql._fraiseql_rs.build_mutation_response` takes a selection document
  (format 2) in `entity_selections` and raises `ValueError` without one; its
  `success_type_fields` and `error_type_fields` arguments are ignored. The
  extension exports `MUTATION_SELECTION_FORMAT`, and fraiseql refuses an
  extension built for another format (a stale build in a development checkout)
  with a `RuntimeError` asking to rebuild it. `execute_mutation_rust` takes
  `selections=` in place of `success_type_fields=`, `error_type_fields=` and
  `entity_selections=`; without it, the response is unfiltered.
### Changed

- **The Rust extension no longer exports `Arena` or `test_snake_to_camel`**
  (#579). They were test helpers registered in the production module. The
  zero-copy response path (used when there is no schema registry or type name)
  converts keys into a buffer it reuses instead of a bump arena, which also
  removes the arena's `unsafe` code. Its `core_benchmark` transforms run 8 to
  14% faster.

### Fixed

- **On CPUs without AVX2 (ARM64 included), the zero-copy path upper-cased the
  letter after a digit that follows an underscore** (#579): `a_1b` became `a1B`.
  It is now `a1b` everywhere, as with AVX2 and in the other camelCase paths.
### Fixed

- **The query plan cache shared one plan between queries that differ only in an
  argument value, and a cache hit returned no parameters** (#580).
  `RustQueryBuilder.build_cached` (`build_sql_query_cached`) keyed plans by
  argument names, so `users(where: {email: {eq: "a@x"}})` and `... "b@x"}}` got
  the first one's SQL, with an empty parameter list. Plans are now keyed by
  argument values too and keep their parameters.
- **A mutation result returned as plain JSON with status `new`, `completed`, `ok`
  or `validation:*` was read as an entity** (#580). Format detection didn't know
  these statuses (`new` is what `mutation_created()` returns), so the whole
  object became the entity of a success. Results of the 8-field
  `mutation_response` type were not affected.
- **An error status with an empty reason (`failed:`) gave an empty `identifier`
  in the `errors` array** (#580); it is `general_error`, as for `failed`.
- **The opt-in `/graphql/rust` endpoint's complexity limit truncated the depth
  multiplier** (#580): a field at depth 1 cost 1 × its cost instead of 1.5 ×. A
  fractional cost now rounds up. Fragment cycles are reported as a closed path
  (`FragA -> FragB -> FragA`), the same one on every run.

### Removed

- **Unused Rust modules** (#580): `db::query`, `db::where_builder`,
  `security::{config, csrf, validators}` and `response`. Nothing called them, and
  none was reachable from Python.
### Fixed

- **`Auth0ProviderWithRevocation` validates tokens.** Its `validate_token`
  recursed until `RecursionError` on every call, so an app using it
  authenticated no one: `super().validate_token` resolves to the revocation
  mixin's own method, which called back into it. It now runs Auth0's validation,
  then rejects a revoked token with `InvalidTokenError`. The class docstring
  showed `RedisRevocationStore`, which fraiseql doesn't have; it shows
  `PostgreSQLRevocationStore`.
### Fixed

- **Auth decorators work when a query has several root fields.** A query
  selecting two or more root fields (`{ me { id } projects { id } }`) runs on
  fraiseql's multi-field path, which passes each resolver its own resolve info
  rather than graphql-core's `GraphQLResolveInfo`. `requires_auth`,
  `requires_role`, `requires_permission`, `requires_any_role` and
  `requires_any_permission` checked the class and answered every decorated field
  in such a query with "First argument must be GraphQLResolveInfo", although
  each field queried alone worked. They now accept either; the checks they make
  on the user are unchanged.
### Fixed

- **ltree depth filters render valid SQL.** `nlevel`, `nlevel_eq`, `nlevel_neq`,
  `nlevel_gt`, `nlevel_gte`, `nlevel_lt`, `nlevel_lte` and their `depth_*` aliases
  (GraphQL `depthGt`, `nlevelLte`, ...) failed with a PostgreSQL syntax error on a
  `db.find` where, on an `ltree` column and on a JSONB field alike: `depth_gt`
  rendered `"path" depth > %s` and `nlevel_gt` rendered `"path" nlevel({}) > %s`.
  They now render `nlevel(path) > %s`, with the JSONB value cast to `ltree`.

## [1.29.1] - 2026-10-19

### Fixed

- **The mutation naming warnings promised renames in a 2.0.0 release.** That
  version exists on PyPI: fraiseql 2.x is the separate FraiseQL v2 project, so
  there is no 1.x major release to rename in. fraiseql 1.x keeps the names it
  has. The `FutureWarning` now lists each mutation still named after its
  `function=` or success type with its preferred name, and promises no rename:

  ```text
  These mutations are named by fraiseql's legacy rule (a field after its function=, a result union after its success type):
    field 'fnCreatePost' (preferred: 'createPost')
    result union 'PostResult' (preferred: 'UpdatePostTitleResult')
  fraiseql 1.x keeps these names. To choose a name and silence this warning, pass name="..." (field) or result_name="..." (union) to @mutation.
  ```

  `fraiseql.result()` stays deprecated, with no removal version. The docs, the
  decorator docstrings and the 1.29.0 notes below are corrected the same way.
  A `warnings.filterwarnings(message="These mutation names will change")` written
  for 1.29.0 no longer matches; filter on the new text, or on `FutureWarning`
  and your module. Filters on the category or module alone are unaffected.

## [1.29.0] - 2026-10-18

Corrected in 1.29.1: these notes first said the legacy names would change in a
2.0.0 release. fraiseql 2.x is the separate FraiseQL v2 project; 1.x keeps the
names.

### Upgrading

- **Mutation names.** A class mutation is named after its class
  (`CreatePost` -> `createPost`), and its result union after its field
  (`updatePostTitle` -> `UpdatePostTitleResult`). fraiseql 1.x keeps the
  current names of a mutation that works today, so nothing is renamed by
  upgrading. Where a name comes from the legacy rule (`function="fn_create_post"`,
  or a union named after its success type such as `PostResult`), the schema
  build emits one `FutureWarning` listing each one with its preferred name (the
  1.29.1 wording is shown under 1.29.1 above).

  Pass `name=` / `result_name=` with the current name to keep it, or with the
  preferred one to switch; either removes the mutation from the warning. The
  warning points at your `build_fraiseql_schema()` / `create_fraiseql_app()`
  call, so it can be filtered by module.
- **Mutations that clashed** (two classes sharing `function=`, or two mutations
  sharing a success type) used to lose a field or fail the build. They get the
  preferred names straight away, with no warning.
- **`fraiseql.result()`** is deprecated; annotate `Success | Error` instead.
- **Rust-built mutation responses are stricter.** Nested entities under an
  interface or union field are filtered to the fields their fragments select,
  and `"__typename": "Entity"` becomes the real type name or is left out. See
  Fixed below.

### Added

- **`@mutation(name=...)` sets a mutation's GraphQL field name.** The name is
  used as given. It works on class and function mutations.
- **`@mutation(result_name=...)` sets the name of a mutation's result union.**
  An auto-discovered mutation takes `result_name:` in its `@fraiseql:mutation`
  comment.

### Fixed

- **Two class mutations with the same `function=` left one field.** The field
  was named after the SQL function, so `CreateThing` and `CreateThingEnriched`,
  both with `function="create_thing"`, gave one `createThing` field served by
  whichever class was registered last. Each class now gets its own field, named
  after the class (`createThing`, `createThingEnriched`), and both call the
  shared function. Two mutations that end up with the same field name make the
  schema build raise a `ValueError` naming both.
- **Two mutations sharing a success type failed the schema build.** The result
  union was named after the success type, so both got `CreateThingResult` and
  graphql-core raised `Schema must contain uniquely named types but contains
  multiple types named 'CreateThingResult'`. Each mutation now gets its own union,
  named after its field (`CreateThingResult`, `CreateThingAgainResult`), with the
  same or different error types. Two mutations with the same union name make the
  schema build raise a `ValueError` naming both. A success type shared by a
  cascade mutation and a non-cascade one shows the `cascade` field on both
  (`null` on the latter).
- **A function mutation could replace a class mutation calling a function of
  the same name, or the other way round.** A function `create_thing` and a class
  `MakeThing` with `function="create_thing"` shared a registry entry, so the one
  registered last was the only one in the schema. Both are kept now:
  `createThing` (the function) and `makeThing` (the class).
- **A schema with auto-discovered mutations failed to build.** The input class
  generated for a discovered function was a plain class, so the build raised
  `Invalid type passed to convert_type_to_graphql_input`. This hit both kinds of
  function: plain `p_` parameters and an `input_payload JSONB` described by a
  composite type. The class is now made an input type the way `@fraiseql.input`
  does it, and descriptions from the composite type's column comments reach the
  schema.
- **A mutation entity behind an interface got the interface's name as its
  `__typename`.** For a nested field typed as an interface (`owner: Node`), the
  Rust pipeline filled `__typename` from the schema, so the response said
  `"__typename": "Node"`, which is not a type an object can have. It now comes only
  from the data. Responses from the Rust pipeline keep including `__typename` on
  objects of a known type even when it was not selected; this is now documented
  as deliberate (see "Python ↔ Rust Integration").
- **A mutation entity selected through a named fragment came back empty.**
  `location { ...LocationFields }` returned only `__typename`, and a fragment
  spread inside `... on XSuccess` dropped the entity. The spread's name was read
  as a field name. Spreads are now expanded.
- **Fields selected through fragments under a nested interface or union field
  were ignored.** With `owner { ... on Person { name } }` in a mutation entity,
  the nested object came back with every column of its view, so a mutation could
  return fields nobody selected; with `owner { id ... on Person { name } }`,
  `name` was dropped. They are now selected, and `owner { __typename }` returns
  only `__typename`. Responses get stricter: a client that read an unselected
  field there no longer gets it. Until per-type filtering lands, each object keeps
  the fields of every fragment under that field.
- **A mutation entity whose SQL function returned no `entity_type` was given
  `"__typename": "Entity"`**, a type not in the schema. It is now named after the
  success type's entity field (`Location`), or left without `__typename` when that
  field is an interface or union and the data has none; a warning names the SQL
  function, once. The 8-field `mutation_response` path now uses the type Python
  passes, which it used to drop. Response bytes change: a client that keyed on
  `"Entity"` gets the real type name, or no `__typename`.

### Deprecated

- **Mutation field names taken from `function=`.** A class mutation is named
  after its class: `CreatePost` -> `createPost`. In fraiseql 1.x, one whose
  `function=` differs (`fn_create_post`) keeps the name it has today
  (`fnCreatePost`), and the schema build emits one `FutureWarning` listing every
  such field. Pass `name=` to keep the current name or switch to the preferred
  one. For an auto-discovered mutation, the preferred name is the `name:` in
  its `@fraiseql:mutation` comment, which was ignored until now.
- **Result union names taken from the success type.** A mutation's union is
  named after its field: `updatePostTitle` -> `UpdatePostTitleResult`. In
  fraiseql 1.x, a working mutation whose union was named after its success type
  (`PostSuccess` -> `PostResult`) keeps that name and is listed in the same
  `FutureWarning`. Pass `result_name=` to keep the current name or switch to the
  preferred one. The warning is reported at your `build_fraiseql_schema()` or
  `create_fraiseql_app()` call, not inside fraiseql, so you can filter it by
  module.
- **`fraiseql.result()`.** It emits a `DeprecationWarning` and keeps working in
  fraiseql 1.x. Annotate `Success | Error` instead. Its type stub now has the
  real signature, `result(success_cls, error_cls)`, and is marked `@deprecated`,
  so type checkers flag calls too.

### Removed

- **Examples `compliance-demo`, `multi-tenant-saas`, `ecommerce_api`, `admin-panel`
  and `real_time_chat`.** They were written against APIs fraiseql doesn't have.
  `blog_api` and `context_parameters` build on the current API;
  `saas-starter` and `ecommerce` are being fixed (#565). For subscriptions, see
  `websocket_fastapi.py`.

## [1.28.0] - 2026-10-17

### Added

- **A mutation's `prepare_input` hook can be `async`, and can take `info`** (#557).
  An async hook is awaited, so it can enrich the input with I/O (an outbound
  HTTP call, say) before the PostgreSQL function runs. A hook that takes a
  second positional parameter receives the resolver's `info`, so a client can
  come from `info.context`. The hook runs before a pool connection is
  acquired. Existing one-argument sync hooks behave as before.

### Fixed

- **`fraise_field` fields failed in modules using `from __future__ import
  annotations`.** There every annotation is a string, and a field assigned
  `fraise_field(...)` -- such as `items: list[Item] = fraise_field(default_factory=list)`
  -- took the string as its type, so building the schema raised `Unsupported
  output type: list[Item]`. Plain annotations and `Annotated[..., fraise_field()]`
  were not affected. Annotations are now resolved first, for `@fraiseql.type`,
  `@fraiseql.input`, `@fraiseql.interface` and the mutation result types.
- **A query with several root fields lost a field that used a named fragment
  spread.** `query { products { ...ProductFields } productsCount }` returned
  `products: []` with `Fragment 'ProductFields' not found` (#554). The
  multi-field path built each resolver's `info` with no fragments, so
  `db.find()` could not expand the spread. The resolvers now get the
  document's fragments, the executed operation and a real `path`, and the
  request's `operationName` selects the operation when the document holds
  several.
- **The error for an annotation naming an undefined type suggested a fix that
  doesn't work.** It said to use `from __future__ import annotations`, but the
  decorator resolves annotations as it runs, so that raises the same error.
  It now says to define the type first at module level, or import it there.

## [1.27.1] - 2026-10-17

### Security

- **Field-level authorization on the resolver-bypass paths lost arguments given
  as variables, on graphql-core 3.3.** The Rust merge, passthrough,
  TurboRouter, `POST /graphql/rust` and APQ-cache paths re-check
  `authorize_fields` before serving data, passing each gated field's arguments
  to the authorizer. graphql-core 3.3 (what `graphql-core>=3.2.12` resolves to)
  changed `get_argument_values` to take a `VariableValues` instead of a dict,
  so with any argument given as a variable the call raised and the arguments
  became `{}`. A policy that denies on an argument value -- such as a `where`
  filter on a gated list field -- then allowed the request, and two selections
  that differed only in their variables were checked once. Variables are now
  coerced against each operation's definitions first, as execution does, and
  variables that don't coerce are rejected. graphql-core 3.2 was not affected.
  Affects 1.23.6 through 1.27.0. (GHSA-f94w-r8x8-c3mx)

### Fixed

- `debug_graphql_info` raised `AttributeError` on graphql-core 3.3 when the
  operation had variables. (#550)

### Internal

- CI installs from `uv.lock`, with ruff 0.17.1 and ty 0.0.89, and `pytest -n
  auto` no longer fails tests that depend on what ran before them. (#550)

## [1.27.0] - 2026-10-17

### Added

- **Python 3.14 support**, alongside 3.13 (`requires-python = ">=3.13,<3.15"`).
  Each platform now gets cp313 and cp314 wheels, so 3.14 users don't need a
  Rust toolchain, and CI runs the unit tests on both interpreters. confiture
  supports 3.14 only from 1.30.0, which in turn requires 3.14, so the
  `migrate` extra is split by interpreter: `fraiseql-confiture>=0.44.0,<1.30`
  on 3.13 and `fraiseql-confiture>=1.30.0` on 3.14. (#546)
- **`fraiseql migrate` runs `.up.sql` / `.down.sql` migrations**, alongside the
  `.py` migrations `migrate create` writes, in one directory. (#548)

### Fixed

- **`fraiseql migrate` failed at import on a fresh 1.26.0 install.** 1.26.0
  allowed any `fraiseql-confiture>=0.44.0`, and from confiture 1.16.0 the
  migration loader it imported is private, so on 3.13 (which resolves
  confiture 1.29.0) every `fraiseql` CLI command raised `ImportError: cannot
  import name 'get_migration_class'`. `up`, `down` and `status` now go through
  confiture's public `MigratorSession`, and nothing fraiseql imports from
  confiture is private. confiture's contract tests now pin that surface, from
  1.38.0. (#546, #548, fraiseql/confiture#737)
- **A pending `.up.sql` migration crashed `migrate up` and `migrate down`,**
  which loaded it as Python. `status` also listed only `.py` files. (#548)
- **`migrate up` skipped confiture's safety checks**: the migration lock (two
  concurrent runs could both apply a migration), checksum verification, and
  the superuser, destructive and non-transactional gates. The session runs
  all of them. (#548)
- **A failed `migrate up` or `migrate down` exits non-zero** with confiture's
  error message, printed once. (#548)
- **On Python 3.14, `to_dict()` on an `@fraiseql.input` object returned `{}`**,
  and mutations raised serializing input objects: both read
  `__annotations__` from the instance, which PEP 749 no longer allows. (#546)

### Changed

- **Breaking: `fraiseql migrate` needs the new `migrate` extra.** confiture
  moved from the runtime dependencies to `fraiseql[migrate]`, because since
  confiture 1.16.0 it depends on [pglast](https://github.com/lelit/pglast),
  which is GPL-3.0-or-later. Every 3.14 install would have pulled it in, as
  fresh 3.13 installs of 1.26.0 already did. A plain `pip install "fraiseql<2"`
  now installs no GPL code. If you use `fraiseql migrate`, install
  `pip install "fraiseql[migrate]<2"`. Without the extra, `migrate up` and
  `down` exit with that command, `status` prints it and lists the files, and
  `init` and `create` work as before. `fraiseql[all]` and `fraiseql[dev]`
  include the extra.
- **`fraiseql migrate init` writes `database_url:`** in
  `db/environments/local.yaml` instead of a `database:` mapping, since
  confiture's `Environment` accepts only the URL. Existing files with a
  `database:` mapping keep working: fraiseql converts the mapping to a URL with
  the same defaults as before (localhost, 5432, user and database `postgres`,
  empty password). (#548)
- **`migrate up` / `migrate down` report what was applied or rolled back**
  (`Applied <version>_<name>`, `Rolled back ...`, `Skipped ...`) after the run,
  instead of printing before each step. (#548)
- **Dependency floors raised.** Runtime: `graphql-core>=3.2.12` (fresh installs
  get 3.3), `starlette>=1.6.0`, `uvicorn>=0.53.0`, `python-dateutil>=2.9.0.post0`.
  Development: `langchain-core>=1.6.3`. (#545)

### Security

- **Floors raised past 41 advisories in 11 packages.** Runtime: `urllib3>=2.8.0`,
  `pyjwt>=2.15.0` (also in the `auth0` extra), and `anyio>=4.14.2` through a
  constraint. Extras: `werkzeug>=3.1.9`, `banks>=2.5.1`, `pypdf>=6.19.0`, and
  constraints on `multidict`, `fsspec`, `tinytag` and `langgraph-sdk`.
  Development: `virtualenv`. (#545)
- **A pyjwt advisory has no fixed release.** PYSEC-2026-4146: `jwt.decode()`
  mutates a caller-supplied `options` dict when `verify_signature` is falsy,
  so a dict reused across calls carries the change into later decodes.
  fraiseql's only unverified decode passes a fresh dict on every call, so the
  dependency audit ignores the advisory until a fixed release exists. (#545)

### Documentation

- **The `fraiseql migrate` reference matches the CLI.** `docs/core/migrations.md`
  documented options that never existed (`up --steps`, `up --dry-run`,
  `down --force`, `init --path`) and `001_name.sql` files under `migrations/`.
  It now documents the `db/` layout `init` creates, timestamped `.py` and
  `.up.sql` migrations, and the real options.

### Internal

- `uv.lock` pins confiture 1.38.0 on 3.14, the first release whose contract
  tests cover fraiseql, and 1.29.0 on 3.13, the release a fresh 3.13 install
  resolves. It pinned 0.45.0 before, which is why CI missed the 1.26.0 import
  failure.
- Tests no longer mock graphql-core AST nodes with `MagicMock(spec=...)`,
  which stopped working in graphql-core 3.3. (#545)
- pre-commit pins `toml-sort==0.24.4`, so pre-commit.ci stops reformatting
  `uv.lock`. (#545)
- ruff 0.17 conventions: `import datetime as dt`, combined `async with`. (#545)

## [1.26.0] - 2026-09-15

### Fixed

- **Session variables never reached PostgreSQL.** With
  `session_variables={"locale": "app.locale"}` and a `context_getter` returning
  `{"locale": ...}`, a view reading `current_setting('app.locale', true)` always
  took its fallback. The request context was never copied into the repository,
  and no read method applied session variables at all. The router now copies
  every key a session variable is read from into `context["db"].context` -- on
  POST, GET, `/graphql/rust` and the multi-field merge path -- and `find()`,
  `find_one()`, `count()`, `exists()`, `sum()`, `avg()`, `min()`, `max()`,
  `distinct()`, `pluck()`, `aggregate()` and `batch_exists()` apply them on
  their own connection before the query, scoped to its transaction.
  (#534, #535)
- **Setting session variables from a context with `user_id` but no `roles`
  aborted the transaction.** The `app.is_super_admin` lookup ran
  `SET LOCAL app.is_super_admin = EXISTS (...)`, which PostgreSQL rejects
  because a `SET` value cannot be an expression, and the fallback then failed
  with `InFailedSqlTransaction`. Only the bug above had kept it unreachable on
  the standard router. `app.is_super_admin` is now `'false'` when `roles` is
  absent. `roles` given as role names -- the shape of `UserContext.roles` -- no
  longer raises `AttributeError`, and a `None` context value is skipped instead
  of being sent as the string `'None'`. (#535)
- **`fraiseql init` followed by `fraiseql dev` did not serve a query.** `dev`
  could not import the default `src.main:app` (`No module named 'src'`); the
  generated `src/main.py` read `DATABASE_URL` while `.env` wrote
  `FRAISEQL_DATABASE_URL`; the generated project depended on an unpinned
  `fraiseql`, so installing it pulled v2; `FRAISEQL_DEV_AUTH_PASSWORD` was
  active, so the first query returned 401; and the template resolver raised
  `takes 2 positional arguments but 3 were given`. Generated projects now also
  ship a `docker-compose.yml` (PostgreSQL on port 54320) and a seed schema, and
  `dev` reports an unreachable database once instead of repeating the
  traceback. (#527)
- **The package metadata sent PyPI visitors to v2.** Homepage, Repository,
  Issues and Changelog in `[project.urls]` resolved to `fraiseql/fraiseql`, and
  Documentation to `fraiseql.dev` -- both the v2 project. They now point at
  this repository and at the v1 documentation on GitHub Pages. (#525, #539)

### Changed

- **Built-in session variables are now set on the standard router.** An app
  whose `context_getter` returns `tenant_id`, `contact_id`, `user_id` or
  `roles` now gets `app.tenant_id`, `app.contact_id`, `app.user_id` and
  `app.is_super_admin` on every query and mutation, as the documentation
  already described. Views and RLS policies that read them will start
  filtering. On a pooled connection, once any transaction has set a custom
  variable, `current_setting(name, true)` returns `''` rather than `NULL`, so
  wrap it in `NULLIF(..., '')` before a `COALESCE` or a cast; the
  `session_variables` and RLS examples in the docs now do. (#535)
- **Session variables are set in one round trip.** One `SET LOCAL` per
  variable became a single `SELECT set_config(%s, %s, true), ...` with bind
  parameters, so variable names are no longer interpolated into SQL. This
  covers reads, `run()`, `execute_function*()`, mutations and turbo, and
  `pg_stat_statements` now records the `set_config` statement. An app that
  maps no session variable sends nothing extra. (#535)
- **Dependency floors raised.** Runtime: `psycopg-pool>=3.3.1` and
  `fraiseql-confiture>=0.44.0`. The `tracing` and `all` extras:
  `opentelemetry-exporter-otlp>=1.44.0` and `protobuf>=7.36.1` -- a new major,
  so an application that pins protobuf below 7 can no longer install them. The
  `langchain` extra: `langsmith>=0.11.2`. Development tooling: `twine` 7,
  `pytest-asyncio` 1.4, `psutil`, `pymdown-extensions`. (#523, #538)

### Security

- **`banks` raised to 2.4.5** for GHSA-x8wg-4xgc-vr54 / CVE-2026-71492, a path
  traversal in `DirectoryPromptRegistry.set()`. It arrives with the
  `llamaindex` extra, and so with `llm` and `all`. (#536)
- **An nltk advisory has no fixed release.** PYSEC-2026-3740 /
  GHSA-8mgp-746c-j5xp / CVE-2026-81726 affects every nltk release through
  3.10.3, in its model-persistence APIs. nltk comes in only through
  `llama-index-core` in the `llamaindex`, `llm` and `all` extras; fraiseql
  never imports it, and llama-index-core does not use the affected APIs. The
  dependency audit ignores the advisory until a fixed release exists. (#536)
- **Vulnerability reports were routed to the v2 project.** `SECURITY.md`
  pointed the security-advisory form and the known-issues list at
  `fraiseql/fraiseql` and listed 1.0.x and 0.11.x as supported. It now points
  at this repository and states what is supported: the latest 1.x release,
  with no backports. The security contact is security@fraiseql.dev
  everywhere. (#525, #527)

### Documentation

- **Install commands pin `fraiseql<2`.** v1 and v2 share the `fraiseql` name
  on PyPI, and the bare name installs v2. The README and 67 install commands
  across 34 docs pages now pin `<2`, quoted so the shell does not read it as a
  redirect. (#524, #526)
- **The README was rewritten**, from 1155 lines to 200. The performance claim
  is now the 3.6-5.9x measured on 1.25.0; the "7-10x" it replaced was measured
  against v0.11.5. (#524)

### Internal

- **`test_nested_organization_without_tenant_id` had failed since 2026-05-14
  without anyone seeing it.** Its stub turned `mandatory_filters` into a column
  name, its error check only failed on messages mentioning `tenant_id`, and
  both tests skipped themselves under `GITHUB_ACTIONS`, so CI never ran the
  file. It now runs in CI against the shared test database. (#516, #517)
- The documentation build installs D2 without `--tala`, which the installer
  stopped accepting. (#537)
- Dropped `target-features` from the `fraiseql_rs` build dependencies; the
  build script never used it. (#538)

## [1.25.0] - 2026-08-30

### Added

- **`default_string_collation` now reaches the query.** The setting is
  documented as applying to "all text fields in ORDER BY unless overridden
  per-field" and had never affected a sort. #481 deliberately left it inert,
  because nothing in the `order_by` pipeline knew which fields were text and a
  blanket default would have produced a silently lexicographic sort for a
  numeric JSONB field (1, 10, 2) and `collations are not supported by type
  integer` for a numeric flat column. Sort paths are now resolved against the
  source type's annotations, and the default applies only to `str` leaves.
  Anything unresolved -- an unregistered view, an aggregation prefix, an
  undeclared field -- keeps the behaviour it had. (#482, #502)

### Fixed

- **`OrderBy.collation` was applied by none of the three paths that render a
  sort key.** Both flat-column branches returned before the `COLLATE` block ran
  and dropped the clause outright. The JSONB branch emitted
  `data -> 'name' COLLATE "x"`, which parses as `data -> ('name' COLLATE "x")`
  -- `COLLATE` binds tighter than `->`, so the collation attached to the key
  literal, the comparison stayed `jsonb`, and PostgreSQL accepted it in
  silence. Every collatable branch now routes through one helper. Note that a
  collated sort is a text sort, so an explicit JSON null now sorts with an
  absent key rather than ahead of every string. (#476, #481)
- **`order_by` given as a list of dicts did not recurse into nested fields.**
  `{"measures": {"cost": "desc"}}` sorted correctly; the same value wrapped in
  a list sorted by `measures ASC` -- wrong field and wrong direction, with no
  error. The list branch had its own shallower parser that handed the nested
  dict to the direction normaliser, which does not recognise a dict and
  returned the ASC default. Both shapes now walk the same collector, and a
  value neither shape can read warns and is dropped instead of silently
  defaulting to ASC. (#475, #484)
- **Schema-qualified view names rendered as one quoted identifier containing a
  dot.** A view registered as `myschema.v_stats` has to become
  `"myschema"."v_stats"`; passing the whole string to a single-argument
  `Identifier` produced `"myschema.v_stats"` and the statement failed with
  `relation "myschema.v_stats" does not exist`. Fixed across every site in
  three passes: the partial-period UNION branch builders plus eleven repeated
  copies in `db.py` (#472, #485), cursor pagination, reachable from any
  `@connection` query (#486, #487), and the SQL, mutation and langchain
  generators (#488, #489). The splitting helper now lives in
  `sql/identifiers.py` as `qualified_identifier`, so there is one spelling of
  it.
- **The langchain vector store's read path interpolated five
  constructor-supplied names as bare text.** `asimilarity_search` built its
  statement as an f-string while the two write paths rendered the same names
  through `psycopg.sql`, so the same constructor arguments were accepted on
  write and rejected on read: an unquoted name is folded to lower case, so any
  name needing quotes -- mixed case, a reserved word, a hyphen -- resolved one
  way and failed the other. Request-controlled values were already
  parameterised. (#490, #492)
- **Three of the six `VectorOrderBy` distance operators were unusable, and the
  two `order_by` shapes disagreed about which.** The dict shape emitted no
  instruction at all for `l1_distance`, `hamming_distance` and
  `jaccard_distance`, so the query ran unsorted and returned rows in scan
  order; the `__gql_fields__` shape emitted a JSONB path sort against a vector
  column, which the server rejects. The bit-string operators also emitted a
  second, contradictory `DESC` term, because a `VectorOrderBy` was handled and
  then recursed into as a nested input. Both shapes now read one operator tuple
  and append through one helper. (#483, #493)
- **Aggregation `measures` and `native_measures` keys are normalised at
  registration.** Both are matched against dotted field paths built with
  `to_snake_case`, so a key written in GraphQL spelling -- `measures.totalCost`
  -- matched nothing, with no error and no warning. This is the casing trap
  #467 fixed for `native_dimension_mapping` and deliberately left here. (#477,
  #496)
- **Vector distance filters are now boolean WHERE predicates.** All six
  operators rendered a bare distance expression -- a `double precision` -- so
  PostgreSQL rejected any WHERE clause containing one with `argument of WHERE
  must be type boolean`. The distance is now wrapped in the requested
  comparison, and every accepted input shape is normalised through one
  function. The root cause was diagnosed first by
  [@mikemikimike](https://github.com/mikemikimike) in #509, whose approach this
  builds on. (#505, #511)
- **`custom_distance`, `vector_norm`, `quantized_distance` and `reconstruct`
  are refused in a WHERE clause** instead of rendering an expression that is
  not a predicate. None of the four ever executed: `vector_norm` emitted a
  two-argument call to a pgvector function that takes one, and the quantized
  pair name functions FraiseQL does not define. `custom_distance` and
  `quantized_distance` also concatenated caller-supplied strings into the
  statement through `psycopg.sql.SQL()`, which does not escape; neither was
  reachable from a GraphQL request, since `VectorFilter` declares no such
  field. They stay registered so the rejection raises `WhereClauseError` rather
  than being swallowed as an unsupported operator, which would drop the filter
  and widen the result set. (#510, #512)
- **Jaccard distance renders as a function call rather than the `<%>`
  operator**, which psycopg rejects as a placeholder whenever the statement
  carries parameters. (#495, #507)
- **Both operands of a bit distance carry the literal's width.** A bare
  `::bit` is `bit(1)`, so the distance was computed over a single bit and every
  row reported 0. (#494, #504)
- **The Rust benchmark targets compile, and CI keeps them compiling.** The
  benches had drifted past the API they call and no job built them.
  [@Joemon24](https://github.com/Joemon24) identified the same drift and posted
  equivalent source fixes in #491 two hours before this landed. (#471, #500)
- **`DATABASE_URL` no longer leaks out of the example fixtures into later
  tests.** Two fixtures set six environment variables with bare
  `os.environ[...]` and never restored them, so a CLI test that should fail on
  a missing argument instead connected to whatever server the inherited URL
  named. (#470, #497)

### Removed

- **`VectorOrderBy.custom_distance` and `.vector_norm`** -- declared GraphQL
  input fields that nothing read, so a client could send either and get no
  `ORDER BY` term and no error. (#512)
- **`fraiseql.security.startup_checks`**, a security module nothing imported.
  It could not have been wired in as written: `disable_sqlite_fts5()` was a
  no-op calling a `Connection` method as though it were module-level,
  `run_all_security_checks()` called `sys.exit(1)` from library code, and two
  further checks raised when running as root. A security control nobody calls
  reads as a control during an audit and enforces nothing. (#473, #499)
- **`aiosqlite` from `[project.dependencies]`** -- installed by every
  `pip install fraiseql` and imported by nothing in the repository. Vestigial
  from the multi-database ambition v1 dropped; v1 is PostgreSQL-only. The
  package remains in the lock as a `llama-index-core` dependency, so the
  `llamaindex` extra still resolves. (#474, #498)
- **Four `fraiseql_rs/tests/` directories**, 423 lines that no cargo target
  reaches in runnable form. `tests/common/` was type-checked through an
  `include!` in `src/lib.rs` but could never execute, because the lib test
  binary cannot link under pyo3's `extension-module`; the other three were not
  cargo targets at all. (#501, #506)

### Security

- **The compliance report's "Unpatched vulnerabilities" counter could only ever
  report 0.** It tested `FixedVersion == ""`, but Trivy omits the key entirely
  when upstream has no fix, so the key read as null and matched nothing -- in
  an artifact stamped "Compliance Level: Government Agency Ready", stating the
  inverse of the truth. A FIXABLE complement was added alongside. (#478, #480)
- **The scan summary now counts UNKNOWN-severity CVEs**, closing a 7-finding
  gap against the Security tab (88 vs 81). The SARIF upload always contained
  them: `severity:` on that step is inert, because trivy-action unsets
  `TRIVY_SEVERITY` for SARIF format. (#508)

### Internal

- Recorded why the Trivy SARIF `category:` must never change: GitHub closes an
  alert only when a later analysis for the same category omits it, so a rename
  strands every alert uploaded under the old one. (#503)
- Added `CONTRIBUTORS.md`, recording external contributions that shaped what
  shipped including work folded into another pull request, and pointed
  `CONTRIBUTING.md` at it. (#513)

## [1.24.0] - 2026-08-30

### Fixed

- **Partial-period aggregate queries silently dropped `OR` and `NOT` filter
  groups, returning too many rows.** On the `UNION ALL` path a coarse view takes
  when it has `fine_grain_view` metadata and the query carries a date lower
  bound, the WHERE clause was rebuilt from its top-level conditions alone —
  discarding every nested group. When the date bound was the *only* top-level
  condition it failed open completely: both branches ran with no filter beyond
  the date range. `mandatory_filters` (#344) was never affected, being injected
  as flat conditions; a deployment that expresses a tenant or authorization
  scope through an `OR` group rather than `mandatory_filters` was. (#468)
- **A date bound that is not a top-level conjunct no longer triggers the
  partial-period rewrite.** `date >= X OR status = 'a'` was rewritten into
  `date in [branch] AND status = 'a'`, dropping every row that matched on the
  date alone. Such queries now take the correct single-statement path. (#468)
- **`order_by` is no longer discarded on the partial-period path.** It was never
  passed to the UNION builder, so the statement always ended in `ORDER BY 1` —
  a positional sort on the serialized JSON — whatever the caller asked for.
  (#468)
- **A declared column mapping is now applied to `WHERE` predicates, not only to
  `GROUP BY`.** A query could group on the flat column while filtering on the
  JSONB snapshot. (#467)
- **A mapping key that matches no field now fails at registration** instead of
  silently doing nothing. Keys accept either the GraphQL or the database
  spelling and are normalised segment-wise to `snake_case`, so a mapping written
  for the Rust engine (`dimensions.dateInfo.date`) works here unchanged — it
  previously matched nothing, with no error, because the key was a valid path
  and the value a real column. (#467)

### Added

- **`column_mapping=` on `register_type_for_view`** — a top-level peer of
  `fk_relationships` that maps a dotted field path to a flat SQL column, applied
  unconditionally to `GROUP BY`, `WHERE` and `ORDER BY` alike.
  `aggregation["native_dimension_mapping"]` is superseded: it keeps working and
  feeds the same resolver, and `column_mapping=` wins where both declare the
  same path. (#467)

### Changed

- **Ordering on a mapped dimension path now sorts on the flat column.** The
  visible effect is **NULL placement**: a jsonb `null` is the lowest jsonb value
  and sorts first, while a SQL `NULL` sorts last in `ASC`, so any row with a
  missing or null mapped dimension moves from one end of the result to the
  other. Non-null values keep their order for the shapes this library produces —
  ISO dates sort lexicographically in chronological order by construction, and
  the generator uses `->` rather than `->>` so a JSON number keeps its type.
  Values do reorder where the snapshot is untyped: a number written as a string,
  or an ISO timestamp whose rows do not share one UTC offset. (#467)
- **Filtering on a mapped path reads the flat column.** Where the column and the
  frozen JSONB snapshot disagree, results change. This is a correction, and it
  is observable — which is why this is a minor release, not a patch. (#467)

### Security

Fifteen Dependabot advisories across five packages, with the exposure stated
rather than implied:

| Package | Advisories | Where it sits |
|---|---|---|
| `sqlparse` 0.5.5 → 0.6.0 | 4 (ReDoS ×2, quadratic grouping, backslash breakout) | Was declared as a runtime dependency but **imported nowhere in `src/`** — only by a script that already degrades without it. Moved to the `dev` group. |
| `nltk` 3.9.4 → 3.10.3 | 5 (path traversal ×3, DNS-rebinding SSRF, ReDoS) | Optional: transitive through the `llamaindex` extra. Not in a default install. |
| `pypdf` 6.14.2 → 6.16.2 | 2 (memory, runtime) | Optional: declared by the `llamaindex` extra. |
| `cryptography` 49.0.0 → 50.0.1 | 1 (Bleichenbacher oracle, PKCS#7 `EnvelopedData`) | Not code FraiseQL calls — the only cryptography API it uses is AES-GCM in the KMS key manager. But `pyjwt[crypto]` puts the package in **every** install, so the floor is now declared on `project.dependencies` and not just on the `kms` extras. |
| `aiohttp` 3.14.1 → 3.14.3 | 3 (OOB heap read, request smuggling, unnegotiated WS frames) | Optional: `dev` extra, transitive via `llama-index-core`. |

- `click` 8.3.1 → 8.5.0 for PYSEC-2026-2132 / CVE-2026-7246, command injection
  in `click.edit()`. FraiseQL's CLI never calls it; the floor moved because the
  package is core. This was **not** a Dependabot alert — it is what the
  dependency-audit job found on its first honest run, see below.
- **The `dependency-audit` CI job was vacuously green.** `pip-audit ... || true`
  swallowed its exit code, and the follow-up check filtered on
  `.vulnerabilities[].severity` — pip-audit emits `.dependencies[].vulns[]` and
  carries no severity field, so the filter matched nothing and printed
  "✅ No critical or high-severity vulnerabilities found" through ten open HIGH
  advisories. pip-audit's exit code is now authoritative.

Container attack surface, measured on the image built from
`Dockerfile --target runtime` with the same Trivy invocation CI uses:

|        | findings | CRITICAL | HIGH | MEDIUM | LOW |
|--------|----------|----------|------|--------|-----|
| before | 139      | 0        | 13   | 76     | 50  |
| after  | 81       | 0        | 0    | 43     | 38  |

- **`curl` removed from the runtime image.** It existed only to answer the
  `HEALTHCHECK`, which now probes with the interpreter already in the image.
  libcurl, libssh2, libnghttp2, libp11-kit and libgnutls go with it.
- **`pip` and `setuptools` removed from the runtime image**, in the same layer
  that installs the wheel. That also removes the only msgpack in the image,
  which was `pip/_vendor/msgpack` rather than a resolved dependency.
- The krb5 and openldap findings **remain**: they are `libpq5`'s dependencies,
  not curl's, and a test now pins that so a future reduction cannot trade
  PostgreSQL connectivity for a lower alert count.
- `.trivyignore` re-baselined; `security-alerts.yml` no longer scans a
  distroless image that was dropped from the build matrix months ago; the
  compliance gate now states its policy and fails on HIGH findings in language
  packages, which are the ones we can actually fix.

### Internal

- One resolver, `fraiseql.sql.native_columns.resolve_native_column`, now answers
  "does this field path have a flat SQL column?" for `GROUP BY`, `WHERE` and
  `ORDER BY`. It had been spelled six different ways across three `build_field`
  closures, three `is_native` checks and the ORDER BY generator, which is how a
  new rule reached some of them and not others.
- `.dockerignore`: `target/` → `**/target/`. The bare pattern matches only a
  top-level directory, so `fraiseql_rs/target/` was being copied into the build
  context and `docker build` ran out of disk before reaching the runtime stage.

## [1.23.12] - 2026-07-28

### Fixed

- **Multi-field GraphQL queries no longer crash when a `find_one()`-backed
  field is combined with a scalar sibling** (e.g. `{ me { … } machinesCount }`).
  The query previously aborted with `'dict' object has no attribute 'bytes'`
  (`find_one()` ran the `RustResponseBytes` null-check on the plain dict that
  field-only mode returns) and/or `'int' object is not an instance of 'str'`
  (a scalar sibling produced a non-string FFI row that aborted the entire
  Rust-side merge). Both paths are fixed; multi-field queries mixing
  `find_one`, `find`, and scalar fields now merge cleanly. (#448)

### Security

- Remediated 21 Dependabot alerts across `pillow`, `pyasn1`, `soupsieve`,
  `langsmith`, `setuptools`, `pypdf`, and `pydantic-settings`. (#445)
- Bumped `cryptography` and `starlette` to resolve security advisories. (#412)
- Bumped `aiohttp` to `>=3.14.1` to resolve security advisories. (#411)

### Documentation

- Overhauled the documentation for v1: removed the v2-only content that had
  been copied into `docs/` and rewrote the remaining guides, tutorials,
  reference, configuration, and operations pages for the FraiseQL v1
  PostgreSQL/FastAPI runtime. Removed the fictional `@FraiseQL.*` API surface
  and the v2 Arrow Flight section, and fixed the landing page and navigation.
  (#417–#436)

### Changed

- Routine dependency and CI maintenance: Rust crate updates (`reqwest`,
  `mockall`, `criterion`, `itertools`), Python dev-dependency updates
  (`black`, `faker`, `pytest-cov`, `pre-commit`, `graphql-core`), and
  GitHub Actions bumps.

## [1.23.11] - 2026-06-14

### Fixed

- **Partial-period aggregation now honors the `lte`/`lt` upper bound.** When a
  type is registered with `fine_grain_view` partial-period awareness
  (`time_grain_column` / `time_grain_trunc`), a `where` date range with both
  `gte` and `lte` previously applied only the lower bound — the upper bound was
  silently dropped and the query returned every period from `gte` through the
  current period (including future periods). The UNION rewrite now threads the
  upper bound through and clamps the upper edge symmetrically to the lower edge:
  a period that straddles `lte` is recomputed from the fine-grain view over
  `[period_start … lte]` rather than returned as a full-period aggregate. This
  fix also removes a latent double-count where a non-aligned `gte` inside the
  current period emitted overlapping fine-grain branches.

## [1.23.10] - 2026-06-13

### Security

- **Upgraded `pyo3` 0.25 → 0.29 in the native Rust extension** — fixes
  **GHSA-36hh-v3qg-5jq4** (HIGH; out-of-bounds read in `PyList`/`PyTuple`
  `nth`/`nth_back` iterators) and **GHSA-chgr-c6px-7xpp** (MEDIUM; missing `Sync`
  bound on `PyCFunction::new_closure` closures). The migration is behaviour-preserving
  (`downcast`→`cast`, `with_gil`→`attach`, `PyObject`→`Py<PyAny>`, opt-in
  `#[pyclass(from_py_object)]`); validated with `clippy -D warnings` and the
  Rust-extension test suite.

### Changed

- **Dependency maintenance** (no functional change to the FraiseQL API):
  - Rust crates: `thiserror` 1→2, `http` 0.2→1.4, `rand` 0.8→0.10, `sha2` 0.10→0.11,
    `lru` 0.16→0.18 (with the necessary `rand`/`sha2` API migrations).
  - Python: `uvicorn` ≥0.49, plus dev-tooling bumps (`pypdf`, `tox`, `langchain`,
    `cyclonedx-python-lib`, `pytest-benchmark`, `testcontainers`,
    `opentelemetry-instrumentation-psycopg`).
  - Adopted `ty` ≥0.0.35 and fixed the diagnostics it surfaces (consolidated the dual
    `ty` pin; explicit `import psycopg.types.json`; `# ty: ignore` on dynamically-typed
    boundary code).

### Tooling

- Added a `cargo` ecosystem to `.github/dependabot.yml` so Rust advisories now get
  automatic update PRs, and bumped GitHub Actions to the Node 24-compatible majors
  (`setup-python` v6, `codeql-action` v4, `action-gh-release` v2).

## [1.23.9] - 2026-06-12

### Fixed

- **Type stub `error_config.pyi` now mirrors the runtime dataclass** (#374). The hand-written
  stub `src/fraiseql/mutations/error_config.pyi` shadows the runtime `error_config.py`
  `@dataclass` for type checkers (ty / mypy / pyright) and had drifted four ways: it declared
  a non-existent **required** field/param `error_as_data_prefixes`, omitted the real fields
  `error_pattern` and `always_return_as_data`, marked **every** `__init__` param required (the
  runtime defaults all of them), and listed methods that don't exist (`is_success` / `is_error`
  / `should_return_as_data` instead of `is_error_status` / `get_error_code`). The documented
  construction `MutationErrorConfig(success_keywords=..., error_prefixes=..., error_keywords=...)`
  was therefore flagged `missing-argument` for the phantom `error_as_data_prefixes` in every
  downstream consumer. Same `.pyi`-drift class as #370. The stub is now marked `@dataclass` so
  checkers synthesize an all-optional constructor from the field defaults, `ALWAYS_DATA_CONFIG`
  is correctly typed as the deprecated factory function (not a constant), and regression tests
  guard the stub-vs-runtime field/method sets going forward.

### Security

- **CVE monitoring** (#369): of the four watched base-image CVEs, only `CVE-2025-14104`
  (util-linux) has an upstream fix — it was already removed from the active `.trivyignore`
  exception list when `python:3.13-slim` picked up the patch (2026-03-14). The remaining three
  (`CVE-2025-6141` ncurses, `CVE-2024-56433` shadow-utils, `CVE-2025-9820` GnuTLS) have no
  upstream fix yet and stay under active monitoring; none is reachable from the GraphQL API
  server. No repository change was required.

## [1.23.8] - 2026-06-12

### Fixed

- **Type stub `__init__.pyi` now carries `@dataclass_transform`** (#370). The hand-written
  stub completely shadows the runtime `.py` for type checkers (ty / mypy / pyright). It
  re-declared the core type decorators *without* `@dataclass_transform`, so a
  `@fraiseql.type`-decorated class's `__init__` resolved to `object.__init__` and **every
  keyword construction** was flagged as `unknown-argument` / `reportCallIssue` (216 such
  diagnostics measured on a mid-size 1.23.x consumer; ~208 false diagnostics removed).
  Restored `@dataclass_transform(kw_only_default=True, field_specifiers=(fraise_field,))`
  on `type` / `input` / `success` / `error` / `interface`, and synced `mutation()` to the
  runtime signature (`enable_cascade`, `authorizer`, `schema: str | None`, and a
  bare-`@mutation` overload).
- **FastAPI block in the stub** no longer trips strict checkers: replaced the PEP 695
  `type X = None` `except`-branch aliases (which collided with the class imported in the
  `try` branch → `reportAssignmentType`) with a plain typed import, and fixed `__all__` to
  export the real `create_fraiseql_app` instead of the phantom `CreateFraiseQLApp`
  (`reportUnsupportedDunderAll`).

## [1.23.7] - 2026-06-07

### Security

- **Upgraded dependencies to resolve known advisories** (all open Dependabot alerts + a
  pip-audit pass):
  - `pyjwt` 2.12.1 -> 2.13.0 — fixes PYSEC-2026-175/177/178/179 (the JWT auth library).
  - `starlette` 0.52.1 -> 1.2.1 (pulls `fastapi` 0.129.0 -> 0.136.3) — fixes GHSA-86qp-5c8j-p5mr.
  - `aiohttp` 3.13.5 -> 3.14.0 — fixes GHSA-hg6j-4rv6-33pg, GHSA-jg22-mg44-37j8 (dev).
  - `idna` 3.11 -> 3.18 — fixes GHSA-65pc-fj4g-8rjx.
  - `langchain-classic` 1.0.1 -> 1.0.7 — fixes GHSA-3644-q5cj-c5c7 (dev tooling).
  - `pymdown-extensions` 10.21 -> 10.21.3 (and `docs/requirements.txt` 10.5 -> 10.21.3) —
    fixes GHSA-62q4-447f-wv8h, GHSA-r6h4-mm7h-8pmq (docs).
  - All 3,462 unit + security/FastAPI integration tests pass on the upgraded stack
    (including the FastAPI 0.136 / Starlette 1.2 major bump).

- **Container compliance gate (government-grade) now passes.** The 2 CRITICAL and HIGH
  findings flagged by Trivy are all unpatchable base-image OS packages (`perl-base`,
  `ncurses`; `FixedVersion: none`) that are never invoked at runtime by the API server. They
  are documented as accepted, monitored risks in `.trivyignore` (CATEGORY 12) per the existing
  exception process, to be removed once Debian ships fixes.

### Notes

- One pip-audit finding remains with no upstream fix: `py` 1.11.0 (PYSEC-2022-42969), an EOL
  transitive of the dev-group `pytest-forked` (used for process-isolation tests). It is not
  installed by the CI dependency-audit extras and is not invoked at runtime.

## [1.23.6] - 2026-06-07

### Fixed

- **Field-level authorization is now enforced on the resolver-bypass paths (issue #366)** —
  closing a silent fail-open
  - `@fraise_type(authorize_fields=[...])` installs a per-field gate on
    `GraphQLField.resolve`. The Rust multi-field merge, JSON passthrough, TurboRouter, and
    `POST /graphql/rust` paths never invoke that resolver, so a gated field could be served
    **without consulting the authorizer**. Each bypass path now re-applies the gate against the
    query's selection set before serving data — fail-closed, decision-cache-aware, using the
    same `"TypeName.fieldName"` identity and the same evaluation core as the resolver path.
  - Because a bypass path has no resolved parent object, an `authorize_fields` policy must be a
    function of `context`, the field identity, and arguments only (the automatic gate already
    calls authorizers this way). A hand-rolled `@authorize_field` that inspects `root` remains
    enforced on the resolver path only. Detection is per-document: a gated field anywhere in the
    request is enforced (conservative over-enforcement for multi-operation documents, never a
    silent allow).
  - New API: `fraiseql.security.field_auth.enforce_selected_field_authorization` and
    `iter_gated_selections`. `TurboRouter`/`EnhancedTurboRouter` gained an optional `schema`
    argument (wired automatically inside `create_graphql_router`) enabling the field gate on
    that path.

- **TurboRouter authorization gate no longer mislabels persisted mutations as queries
  (issue #368)** — a security regression in the #362 turbo gate
  - `TurboRouter.execute` hardcoded `operation_type="query"`, so a **mutation** served via the
    TurboRouter was presented to the `Authorizer` as a *query*, silently defeating write-guards
    that gate on `operation_type`. The operation type and name are now derived from the document
    (via `_derive_operation_info`), exactly as the APQ and `/graphql/rust` gates already do.

## [1.23.5] - 2026-06-06

### Fixed

- **`@field` / `@authorize_field` compose in either decorator order** — a pre-existing
  field-resolver defect, surfaced during the #366 work
  - A field method gated with `@authorize_field` now runs its check and resolver with the
    correct arguments regardless of decorator order (`@authorize_field` outer / `@field`
    inner, or `@field` outer / `@authorize_field` inner) and for any method shape (`self`,
    `self, info`, sync or `async`). Previously the `@field`-outer order silently failed for
    `self`-only methods (the order the docs showed).
  - Auth wrappers no longer mis-report their signature: `@authorize_field` drops the
    `functools.wraps`-set `__wrapped__`, so an outer `@field` (and `inspect.signature`) reads
    the wrapper's real `(root, info, *args, **kwargs)` interface. **Note:** external tooling
    that followed `__wrapped__` on an auth wrapper now sees this real signature instead of the
    inner method's.
  - A sync field resolver gated by an async authorizer (e.g. `field_authorizer_adapter`) no
    longer emits a `RuntimeWarning` or risks an event-loop deadlock: the wrapper is async
    end-to-end whenever the resolver or the check is async, so graphql-core awaits it directly.
  - Internals: a single `invoke_resolver` convention
    (`fraiseql.core.resolver_invocation`) is now the source of truth for how `@field` and
    `@authorize_field` call what they wrap. Fail-closed behavior is unchanged on every deny.

## [1.23.4] - 2026-06-06

### Added

- **Automatic field-level authorization** (#366) — ergonomics follow-up to #362
  - `@fraise_type(authorize_fields=[...])` gates the listed fields with the configured
    operation `Authorizer` automatically, checked with `operation_type="field"` and
    `operation_name="TypeName.fieldName"` before each field resolver runs — no per-field
    `@authorize_field` needed. Narrow opt-in by design (no gate-everything switch)
  - Fail-closed: `field_authorizer_adapter` now normalizes a raising authorizer to a
    `FIELD_AUTHORIZATION_ERROR` deny (parity with the operation path). An explicit
    `@authorize_field` AND-combines with the automatic gate
  - With no authorizer configured the gate is a no-op (byte-for-byte unchanged). The gate
    consults the optional decision cache (#367), which collapses the per-object call volume
    on nested lists; the per-object cost is documented in `docs/security/authorization.md`

## [1.23.3] - 2026-06-06

### Added

- **Optional authorization decision caching** (#367) — performance follow-up to #362
  - `AuthorizationCacheConfig` + `DecisionCache` (exported from `fraiseql` and
    `fraiseql.security`): opt-in TTL+LRU memoization of authorization decisions, wired via
    `create_fraiseql_app(authorization_cache=...)` and installed on
    `SchemaRegistry.decision_cache`; survives schema hot-reload
  - Consulted on every gated path — the resolver wrap, subscriptions, and the three
    resolver-bypass gates (TurboRouter, `/graphql/rust`, APQ) — keyed on
    `(principal_key(context), operation_type, operation_name, stable_hash(arguments))`
  - **Off by default** (always-evaluate is the safe default). Fail-closed is never cached
    around: a raising authorizer is never cached; a `None` principal is never cached;
    non-JSON-serializable arguments fall through to evaluate
  - **Correctness contract:** enable only if the authorizer is a pure function of
    principal + operation + arguments — a non-pure authorizer is served a wrong decision on
    a hit (documented in `docs/security/authorization.md`). TTL-only invalidation (no active
    revoke hook in this version)

## [1.23.2] - 2026-06-06

### Changed

- **`POST /graphql/rust` is now opt-in** (#365) — defense-in-depth follow-up to #362
  - New `FraiseQLConfig.enable_rust_endpoint` flag (default `False`,
    `FRAISEQL_ENABLE_RUST_ENDPOINT`). The Rust passthrough bypasses Python resolvers
    entirely, so the route is mounted only when explicitly enabled; when disabled it is
    not registered (a request 404s). When mounted it is still authorization-gated (#362).
  - ⚠️ **Behavior change:** apps that were calling `/graphql/rust` must now set
    `enable_rust_endpoint=True`, or the endpoint returns 404.

## [1.23.1] - 2026-06-06

### Added

- **Subscription authorization** (#364) — follow-up to the operation PEP (#362)
  - The configured `Authorizer` now gates subscriptions, enforced **once at subscribe
    time** with `operation_type="subscription"`, before the event stream is created. A
    deny (or a raising authorizer) raises a `GraphQLError` during the awaited `subscribe`,
    so the inner generator is never built and the database is never queried. Covers both
    the schema path and the websocket transport (which routes through graphql-core's
    `subscribe`)
  - `@subscription(authorizer=...)` per-operation override, mirroring
    `@query` / `@mutation`; the global default still applies otherwise
  - A returned `decision.filters` is **logged, not silently dropped** on subscriptions
    (no row-scoping semantics on a stream), mirroring the mutation path
  - Per-event re-checking of live streams is explicitly a future opt-in, not this change
  - With no authorizer configured, subscriptions stream byte-for-byte as before

## [1.23.0] - 2026-06-06

### Added

- **First-class operation authorization extension point** (#362)
  - `Authorizer` protocol + `AuthorizationDecision` value type (`allow`/`deny`,
    optional `code`/`message`/`filters`), exported from `fraiseql` and
    `fraiseql.security`; a single decision contract aligned with v2 (#422)
  - `create_fraiseql_app(authorizer=...)` and `build_fraiseql_schema(authorizer=...)`
    install a global default authorizer on `SchemaRegistry.default_authorizer`;
    `@query(authorizer=...)` / `@mutation(authorizer=...)` add per-operation overrides
  - Enforcement around every root query and mutation (sync + async resolvers) with
    **fail-closed** semantics in one shared helper: an authorizer that raises denies,
    a deny becomes a `GraphQLError` with `extensions.code`, and the raw exception is
    never surfaced to the client
  - **Resolver-bypass paths gated**: TurboRouter / persisted queries,
    `POST /graphql/rust`, and APQ cached passthrough all enforce the same authorizer
    before reaching the database / Rust
  - **Row-scoping filter injection**: a query authorizer may return `filters` that are
    AND-merged into the repository's validated, parameterized `mandatory_filters` via
    the repository context (keyed per root field; overlapping columns rejected). On the
    bypass paths a returned filter is logged (rely on session variables + RLS); APQ
    skips the cache when filters are present
  - Authorizer survives schema hot-reload; the legacy `registry._mutations` rewrite
    keeps working during migration
  - Field-level `authorize_field` accepts `AuthorizationDecision | bool` on one contract;
    `field_authorizer_adapter` lets one policy object serve fields and operations
  - New guide `docs/security/authorization.md` and `examples/authorization/`

## [1.22.0] - 2026-05-14

### Added

- **pg_stat_statements integration** (#357)
  - `v_query_stats` SQL view and `get_query_stats()` function with cache hit
    ratio computation, utility statement filtering, and graceful degradation
  - `QueryStatsCollector` Python API with `get_stats()`, `is_available()`,
    `reset_stats()` and global singleton pattern (`init_query_stats()`)
  - `check_query_stats()` optional health check for monitoring endpoints
  - `fraiseql query-stats` CLI command with `--top-n`, `--order-by`, `--reset`
    flags and color-coded cache hit ratios
  - Prometheus integration via `postgres_exporter_queries.yml` custom queries
  - Test container configured with `shared_preload_libraries=pg_stat_statements`

## [1.21.0] - 2026-05-13

### Added

- **Time grain truncation: `semester` and `half_month`** (#1516, #1517)
  - Extend partial-period awareness to support 6-month and ~15-day granularities
  - Custom SQL expressions (`MAKE_DATE` for semester, `CASE` for half_month)
    for non-native PostgreSQL intervals
  - Unblocks `printoptim_backend` v_statistics_semester and v_statistics_half_month views

## [1.20.1] - 2026-05-12

### Security

- **Bump urllib3** to >=2.7.0 — fix headers forwarded across origins and
  decompression-bomb bypass (Dependabot alerts #77, #78)
- **Bump langchain-core** to >=1.3.3 — fix unsafe deserialization via overly
  broad `load()` allowlists (alert #76)
- **Add banks >=2.4.2 constraint** — fix critical RCE via Jinja2 SSTI in
  llama-index transitive dependency (alert #75)
- **Bump cryptography** to >=47.0.0
- **Update .trivyignore** with documented risk assessments for all 30 open
  Trivy container CVEs (GnuTLS, libssh2, krb5, curl — none used by FraiseQL)

### Changed

- **Bump GitHub Actions** — docker/login-action v4, docker/metadata-action v6,
  docker/build-push-action v7, actions/upload-artifact v7
- **Bump dev dependencies** — llama-index >=0.14.21, ruff >=0.15.12,
  opentelemetry-sdk >=1.41.1, aioboto3 >=15.5.0, mkdocs-material >=9.7.6
- **Improve Dependabot config** — group patch+minor updates, group Actions
  updates, reduce PR limits, ignore boto3 major bumps (aiobotocore coupling)

### Housekeeping

- Closed 9 stale automated CVE monitoring issues
- Closed 16 superseded Dependabot PRs
- Merged pre-commit hook updates (pre-commit-hooks v6.0.0, markdownlint v0.48.0)

## [1.20.0] - 2026-05-11

### Security

- **Fix tenant isolation in aggregated queries** (#344) — filters passed as bare
  keyword arguments to `db.find()` (e.g. `tenant_id=...`) were silently dropped
  when auto-aggregation triggered the UNION ALL code path, causing cross-tenant
  data exposure. Introduced `mandatory_filters` — an explicit, identifier-validated
  dict parameter applied in **all** query modes (normal, aggregated, union-all,
  find_one, count, exists, and all utility methods). Credit: @evoludigit.

### Breaking Changes

- `db.find()`, `db.find_one()`, `db.count()`, `db.exists()`, and all utility
  methods no longer accept arbitrary keyword arguments as equality filters.
  Passing unrecognised kwargs now raises `TypeError`. Migrate from:

  ```python
  db.find("v_foo", tenant_id=tid, ...)
  ```

  To:

  ```python
  db.find("v_foo", mandatory_filters={"tenant_id": tid}, ...)
  ```

## [1.19.1] - 2026-05-03

### Fixed

- **`_build_coarse_branch` missing `GROUP BY` clause** (#342) — when the
  UNION ALL partial-period path was triggered, the coarse-grain branch omitted
  `GROUP BY` for native dimension columns, causing PostgreSQL to raise:

  > column "t.date" must appear in the GROUP BY clause or be used in an aggregate function

  The fix tracks `group_by_exprs` separately in `_build_coarse_branch` and
  appends `GROUP BY` exactly as `_build_fine_grain_branch` does. Regression
  tests added in `tests/regression/issue_342/`.

- **Testcontainer Docker skip** — `postgres_container` and Vault container
  fixtures now catch Docker networking failures (veth bridge creation error)
  and call `pytest.skip()` instead of raising an unhandled exception, so the
  test suite reports skips rather than errors when Docker networking is
  unavailable.

## [1.19.0] - 2026-05-03

### Added

- **Partial-period awareness for pre-aggregated time-series views** (#341) — when a
  `date >=` filter falls in the middle of a coarse-grain period (e.g. a monthly aggregate
  view queried from Jan 15), FraiseQL now automatically generates a three-branch
  `UNION ALL` query that returns correct data instead of silently dropping the partial
  leading period:

  - **Branch 1** (partial first period): fine-grain rows from the lower bound to the end
    of its period — only emitted when the lower bound is not period-aligned.
  - **Branch 2** (complete periods): coarse-grain rows for all full periods between the
    partial period and the current one — fast, uses pre-aggregated data.
  - **Branch 3** (current in-progress period): always fine-grain rows for the current
    period up to today, so live data is never stale.

  Opt in by adding three new optional keys to the `aggregation` dict in
  `register_type_for_view`:

  ```python
  register_type_for_view(
      "v_events_month",
      EventDataPoint,
      has_jsonb_data=True,
      aggregation={
          "dimensions": "data",
          "measures": {"data.volume": "SUM"},
          "native_dimensions": ["date"],
          "fine_grain_view":   "v_events_day",   # NEW
          "time_grain_column": "date",            # NEW
          "time_grain_trunc":  "month",           # NEW
      },
  )
  ```

  Supported granularities: `"day"`, `"week"`, `"month"`, `"quarter"`, `"year"`.
  An invalid `time_grain_trunc` raises `ValueError` at registration time (fast fail).
  Omitting the three new keys leaves existing behaviour completely unchanged.

  The UNION path is only triggered when a `date >=` or `date >` filter is present;
  queries without a date lower bound continue to use the single-query path.

## [1.18.0] - 2026-05-03

### Added

- **`native_measures` and `native_dimension_mapping` in aggregation metadata** — two
  new optional keys in the `aggregation` dict passed to `register_type_for_view`, enabling
  fully native SQL aggregation on JSONB views that also expose flat columns:

  - **`native_measures`**: maps JSONB measure paths to flat column names, so
    `SUM` uses `SUM(t."volume")` instead of `SUM((data->'measures'->>'volume')::numeric)`.
    Eliminates JSONB extraction and the `::numeric` cast for aggregated metrics.

  - **`native_dimension_mapping`**: maps deep JSONB dimension paths to flat column names,
    so `GROUP BY` on a path like `dimensions.category.id` resolves to `GROUP BY t."category_id"`
    via a native btree index instead of JSONB extraction.

  Example:

  ```python
  register_type_for_view(
      "v_statistics_day",
      StatisticsDay,
      has_jsonb_data=True,
      aggregation={
          "native_dimensions": ["date"],
          "dimensions": "dimensions",
          "measures": {
              "measures.volume": "SUM",
              "measures.cost": "SUM",
          },
          "native_measures": {
              "measures.volume": "volume",
              "measures.cost": "cost",
          },
          "native_dimension_mapping": {
              "dimensions.category.id": "category_id",
          },
      },
  )
  ```

  Views without these keys are unaffected — fully backwards-compatible (#340).

## [1.16.2] - 2026-04-28

### Fixed

- **`descendantOfId` / `ancestorOfId` not available on `IDFilter`** — fields typed
  as GraphQL `ID` (rather than `UUID`) use `IDFilter`, which was missing the two
  hierarchy operators. Added `descendantOfId` and `ancestorOfId` to `IDFilter` so
  they work regardless of whether the field is declared as `ID` or `UUID`.

## [1.16.1] - 2026-04-27

### Fixed

- **`descendant_of_id` / `ancestor_of_id` on native SQL columns** — when a UUID
  field is registered in `table_columns` (i.e. a real column, not inside the JSONB
  `data` blob), fraiseql uses the `sql_column` lookup strategy for WHERE clauses.
  The hierarchy-operator interception was only wired into the `jsonb_path` branch,
  so native-column fields silently fell through to the standard operator dispatch and
  raised `KeyError`. Fixed by adding the same interception in the `sql_column` branch,
  generating `"field_name"::uuid IN (SELECT id FROM ...)` instead of
  `(data->>'field_name')::uuid IN (SELECT id FROM ...)`.

## [1.16.0] - 2026-04-27

### Added

- **`descendant_of_id` and `ancestor_of_id` ltree hierarchy operators** — filter by
  hierarchy using a UUID instead of an ltree path string. The operator lives on the
  UUID/ID field (e.g. `categoryId`), so callers never need to know the underlying
  ltree path:

  ```graphql
  items(where: { categoryId: { descendantOfId: $categoryId } })
  ```

  FraiseQL resolves the UUID to its ltree path via a nested subquery and generates:

  ```sql
  (data->>'category_id')::uuid IN (
    SELECT id FROM "myschema"."tb_category"
    WHERE path <@ (
      SELECT path FROM "myschema"."tb_category" WHERE id = 'uuid'::uuid
    )::ltree
  )
  ```

  The JSONB value is cast to `::uuid` (not `id::text`) so PostgreSQL can use the UUID
  index on the `id` column.

  **Convention**: column `{entity}_id` resolves to `{schema}.tb_{entity}`. Configure
  the schema via `FraiseQLConfig.default_entity_schema = "myschema"`.

  Both `descendantOfId` (GraphQL camelCase) and `descendant_of_id` (snake_case) are
  accepted as operator names. `UUIDFilter` exposes both fields for GraphQL schema
  introspection.

## [1.15.0] - 2026-04-19

### Fixed

- **`native_dimensions` always injected into GROUP BY** — previously, native
  dimensions were only added to `GROUP BY` when the client explicitly selected
  them as top-level GraphQL fields. Queries that accessed the same column
  through a nested path (e.g. `dimensions.dateInfo.date`) received no `GROUP BY`
  entry for the native column, making `ORDER BY` on it a PostgreSQL error
  ("column must appear in the GROUP BY clause"). Native dimensions are now
  pre-seeded into `GROUP BY` unconditionally, so `ORDER BY {"date": "asc"}` is
  always safe regardless of selection shape.

## [1.14.0] - 2026-04-16

### Added

- **Native SQL column grouping in auto-aggregation** (#337):
  `register_type_for_view()` now accepts a `native_dimensions` key in the
  `aggregation` metadata. Listed columns are grouped via `t."col"` instead of
  JSONB extraction (`data->>'col'`), enabling btree index usage and fixing
  `ORDER BY` errors when the ordered field is a real SQL column on the view.

  ```python
  register_type_for_view(
      "v_orders_by_period", OrderPeriodType,
      has_jsonb_data=True,
      aggregation={
          "native_dimensions": ["period_date", "category_id"],
          "dimensions": "dimensions",
          "measures": {"measures.total": "SUM", "measures.count": "SUM"},
      },
  )
  ```

  Generated SQL changes from:

  ```sql
  -- Before (slow, no index, error-prone)
  SELECT ... FROM v_orders_by_period
  GROUP BY "data"->>'period_date'
  ORDER BY "data" -> 'period_date'  -- ERROR: data not in GROUP BY
  ```

  to:

  ```sql
  -- After (index-friendly, correct)
  SELECT ... FROM v_orders_by_period AS t
  GROUP BY t."period_date"
  ORDER BY t."period_date"
  ```

  Mixed grouping (native + JSONB dimensions in the same query) is fully
  supported. Backward compatible: existing metadata without `native_dimensions`
  behaves identically to before.

## [1.13.1] - 2026-04-08

### Fixed

- **auth: `get_current_user_optional` silently swallows non-auth exceptions** (#325):
  Narrowed the bare `except Exception` to `except AuthenticationError` so that
  non-auth errors (`PermissionError`, `ConnectionError`, `RuntimeError`, etc.)
  propagate instead of being silently treated as "unauthenticated".

- **audit: `SecurityLogger` crashes on `PermissionError`** (#326):
  Wrapped `FileHandler` creation in a `try/except` so the logger falls back to
  stderr-only logging when the log file is not writable. Added
  `FRAISEQL_SECURITY_LOG_PATH` environment variable support for configuring the
  log path without code changes.

### Changed

- **Version is now derived from package metadata at runtime** via
  `importlib.metadata.version()` instead of a hardcoded string in `__init__.py`.
  Removed orphaned `__version__.py` and standalone version management scripts
  (`version_manager.py`, `check_version_consistency.py`, `check_versions.py`).
  The only version check retained is pyproject.toml ↔ fraiseql_rs/Cargo.toml
  consistency (required by maturin), run as part of `make release-check`.

## [1.13.0] - 2026-03-31

### Added

- **Auto-aggregation from type metadata** (#322): `register_type_for_view()` now
  accepts an `aggregation` parameter that declares which fields are measures
  (with aggregation function) and which are dimensions. When `db.find()` detects
  that the GraphQL field selection contains only dimensions and measures (no
  identity fields like `id`), it auto-generates `group_by` and `aggregations` —
  no manual AST walking in resolvers needed.

  ```python
  register_type_for_view(
      "v_statistics_day", DataPoint,
      has_jsonb_data=True,
      aggregation={
          "measures": {"measures.cost": "SUM", "measures.volume": "SUM"},
          "dimensions": "dimensions",
      },
  )

  # Resolver stays clean — auto-aggregates when appropriate
  @fraiseql.query
  async def datapoints(info, where=None) -> list[DataPoint]:
      return await db.find("v_statistics_day", where=where, info=info)
  ```

### Fixed

- **Multi-platform wheel builds**: Release workflow now builds wheels for Linux
  (x86_64), macOS (x86_64 + ARM64), and Windows (x86_64). Previously only a
  Linux wheel was published, causing `uv sync` failures on cross-platform
  resolution.

---

## [1.12.0] - 2026-03-31

### Added

- **Nested `json_build_object` for `group_by` dot-separated paths** (#318): When `group_by`
  uses dot-separated field paths (e.g. `dimensions.date_info.date`), the SQL now generates
  nested `json_build_object()` calls matching the GraphQL type structure. Previously, flat
  keys like `"dimensions.date_info.date"` were produced, which the Rust pipeline couldn't
  project.

### Fixed

- **`is_type_of` rejects plain dicts from resolvers** (#317): Resolvers returning plain
  dicts (e.g. from `db.run()`) are now accepted by `is_type_of` and correctly resolved.
  Previously, `graphql-core` rejected them with "Expected value of type 'MyType' but got:
  dict". Both `is_type_of` (type gating) and `resolve_field` (field value access) now
  handle dicts alongside typed instances.

- **`group_by` results stripped by Rust field projection** (#319): When `db.find()` is
  called with `group_by`/`aggregations`, the Rust pipeline's field projection is now
  skipped. The SQL's `json_build_object()` already returns exactly the requested fields,
  so additional projection was incorrectly stripping all data.

- **Regression test ordering failures**: Added missing `clear_registry` fixtures to
  multiple regression tests that were failing when run as part of the full suite due
  to stale type registrations from prior tests.

---

## [1.11.0] - 2026-03-31

### Added

- **GROUP BY and aggregations in `db.find()`** (#315): `db.find()` now accepts `group_by`
  and `aggregations` parameters, enabling SQL-level aggregation before returning results.
  This avoids returning hundreds of MB of individual rows for high-cardinality views when
  only aggregated measures are needed.

  ```python
  results = await db.find(
      "v_my_view",
      where={"date": {"gte": "2026-01-01", "lte": "2026-03-31"}},
      group_by=["date"],
      aggregations={"total_cost": "SUM(cost)", "total_volume": "SUM(volume)"},
      info=info,
  )
  ```

  Supports nested JSONB field paths (`date_info.date`), multiple aggregation functions
  (`SUM`, `AVG`, `COUNT`, `MIN`, `MAX`, `ARRAY_AGG`, `JSON_AGG`, etc.), and both JSONB
  and non-JSONB tables. Aggregation expressions are validated against an allowlist to
  prevent SQL injection.

### Fixed

- **Rust mutation executor missing session variables** (#309): Session variables are now
  set before the Rust executor path, fixing `NULL` values for `fraiseql.started_at` and
  RLS policy variables on mutations.

- **CI: Container Security Scan SBOM generation** (#314): Replaced broken `aquasec/trivy`
  Docker Hub image (removed upstream) with `aquasecurity/trivy-action` for SBOM generation,
  fixing the Container Security Scan and Security Gate CI checks.

---

## [1.10.1] - 2026-03-18

### Added

- **Configurable session variable forwarding** (#310): New `session_variables` config field
  on `FraiseQLConfig` maps request context keys to PostgreSQL session variables via `SET LOCAL`.
  Enables locale-aware views (`current_setting('app.locale', true)`) and any custom per-request
  PostgreSQL session state without code changes. Variable names are validated against SQL injection.

  ```python
  config = FraiseQLConfig(
      session_variables={"locale": "app.locale", "timezone": "app.timezone"},
  )
  ```

### Fixed

- **Rust mutation executor missing session variables** (#309): The Rust-accelerated mutation
  path (`execute_mutation_rust`) bypassed `_set_session_variables()`, causing `fraiseql.started_at`,
  `app.tenant_id`, `app.user_id`, `app.contact_id`, and `app.is_super_admin` to all be `NULL`
  for mutations. This broke `duration_ms` computation in `core.tb_entity_change_log` and silently
  disabled Row-Level Security policies on the mutation path. Session variables are now injected
  on the connection before the Rust executor is invoked.

- **TurboRouter missing session variables**: TurboRouter queries reimplemented session variable
  injection inline and only set `tenant_id` and `contact_id`, missing `user_id`, `roles`,
  `is_super_admin`, `fraiseql.started_at`, and all custom variables. Now delegates to the
  canonical `_set_session_variables()` method.

- **`set_config()` for `fraiseql.started_at`**: Use `set_config()` via `SELECT` instead of
  `SET LOCAL` to avoid psycopg extended query protocol issues with function calls in SET
  statements.

### Changed

- **Repository cleanup**: Removed v2 artifacts from v1 repository.

---

## [1.10.0] - 2026-03-14

### Added

- **CLI: `validate-mutation-return` command** (#280): New CLI command and library function
  to validate mutation return values against GraphQL schema types at build time or in CI.
  Supports recursive type validation (objects, lists, unions, enums, scalars), NonNull vs
  nullable field handling, union type matching with `__typename` disambiguation, and three
  output formats: human-readable, JSON, and JUnit XML. Available as both
  `fraiseql validate-mutation-return` CLI command and `from fraiseql import validate_mutation_return`
  library function.

- **DB: `fraiseql.started_at` session variable** (#304): `_set_session_variables` now injects
  `SET LOCAL fraiseql.started_at = clock_timestamp()::text` before every query and mutation,
  enabling PostgreSQL functions to compute their own execution duration via
  `clock_timestamp() - current_setting('fraiseql.started_at', true)::timestamptz`. Uses
  `clock_timestamp()` (not `NOW()`) for accurate wall-clock timing including lock waits.

### Security

- **CVE-2025-14104 resolved** (#295, #299): Removed util-linux heap buffer overread exception
  from `.trivyignore` — now fixed in upstream `python:3.13-slim` base image. Updated review
  dates for remaining monitored CVEs (gnutls28, ncurses, shadow).

---

## [1.9.20] - 2026-02-25

### Fixed

- **Scalar fields on `@fraiseql.error` types silently resolve to `None`** (#294): When a
  SQL mutation function returned scalar values (e.g. `datetime`, `str`, `int`, `UUID`) in
  its metadata JSONB (via `jsonb_build_object(...)`), those values were never populated into
  the corresponding fields of an `@fraiseql.error`-decorated class — they always resolved to
  `None`. The root cause was that `build_error_response_with_code` in the Rust pipeline only
  extracted fields from `result.entity` (dict-backed entities like `conflict_machine:
  Machine`), and completely ignored scalar values stored directly in `result.metadata`. Fixed
  by iterating `result.metadata` after `result.entity` and promoting any non-reserved key
  (`errors`, `entity_type`, `entity`, `_cascade`) to the root error response object, applying
  camelCase conversion and field selection filtering consistently with the rest of the pipeline.

---

## [1.9.19] - 2026-02-21

### Fixed

- **Multi-field query with JSONB types returns empty nested fields** (#288): When a GraphQL
  query had 2+ root-level fields and at least one resolver used a JSONB type
  (`@fraiseql.type(jsonb_column=...)`), nested JSONB fields in the response were empty —
  only `__typename` was returned for each nested object. The root cause was that
  `execute_multi_field_query` only passed top-level field names (e.g. `"nested"`) to
  `build_multi_field_response`, causing Rust's `transform_with_selections` to filter out
  all sub-fields (e.g. `"nested.value"`) whose full paths were absent from `selected_paths`.
  Fixed by replacing the shallow field list with a complete recursive traversal via the new
  `_build_field_selections_recursive()` helper, which includes every dot-separated path at
  every nesting depth. Sub-field `@skip`/`@include` directives and aliases at any depth are
  also preserved correctly. Single-field queries are unaffected.

---

## [2.0.0-alpha.2] - 2026-02-06

### Added

**Audit Backend Test Coverage (Complete):**

- PostgreSQL audit backend comprehensive tests (27 tests, 804 lines):
  - Backend creation and schema validation
  - Event logging with optional fields
  - Query operations with filters and pagination
  - JSONB metadata and state snapshots
  - Multi-tenancy and tenant isolation
  - Bulk logging and concurrent operations
  - Schema idempotency verification
  - Complex multi-filter queries
  - Error handling and validation scenarios

- Syslog audit backend comprehensive tests (27 tests, 574 lines):
  - RFC 3164 format validation
  - Facility and severity mapping
  - Event logging and complex event handling
  - Query behavior (always returns empty)
  - Network operations and timeout handling
  - Concurrent logging with 20+ concurrent tasks
  - Builder pattern and trait compliance
  - E2E integration flows for all statuses

**Arrow Flight Enhancements:**

- Event storage capabilities
- Export functionality
- Subscription support
- Observer events integration tests
- Schema refresh tests with streaming updates

**Observer Infrastructure:**

- Storage layer implementation
- Event-driven observer patterns
- Automatic observer triggering

### Fixed

- Removed placeholder test stubs for deferred audit backends
- Enhanced test documentation with clear categories
- Improved error handling in audit operations

### Test Coverage

- Total comprehensive tests: 54+ (27 PostgreSQL, 27 Syslog)
- All tests passing with zero warnings
- Database tests marked for CI integration with proper isolation
- Syslog tests run without external dependencies

### Already Included (Clarification)

Note: The following features are already available in this release and not deferred:

- OpenTelemetry integration for distributed tracing
- Advanced analytics with Arrow views (va_*, tv_*, ta_*)
- Performance metrics collection and monitoring
- GraphQL subscriptions with streaming support
- Real-time analytics pipelines

---

## [2.0.0-alpha.1] - 2026-02-05

### Added

**Documentation (Phase 16-18 Complete):**

- Complete SDK reference documentation for all 16 languages
  - Python, TypeScript, Go, Java, Kotlin, Scala, Clojure, Groovy
  - Rust, C#, PHP, Ruby, Swift, Dart, Elixir, Node.js
- 4 full-stack example applications
- 6 production architecture patterns
- Complete production deployment guides
- Performance optimization guide
- Comprehensive troubleshooting guide

**Documentation Infrastructure:**

- ReadTheDocs configuration and integration
- Material Design theme with dark mode support
- Search functionality with 251 indexed pages
- Zero broken links (validated)
- 100% code example coverage

**Core Features:**

- GraphQL compilation and execution engine
- Multi-database support (PostgreSQL, MySQL, SQLite, SQL Server)
- Apache Arrow Flight data plane
- Apollo Federation v2 with SAGA transactions
- Query result caching with automatic invalidation

**Enterprise Security:**

- Audit logging with multiple backends
- Rate limiting and field-level authorization
- Field-level encryption-at-rest
- Credential rotation automation
- HashiCorp Vault integration

### Documentation Statistics

- **Total Files:** 251 markdown documents
- **Total Lines:** 70,000+ lines
- **Broken Links:** 0
- **Code Examples:** 100% coverage
- **Languages:** 16 SDK references

---

## Contributing

See [ARCHITECTURE_PRINCIPLES.md](.claude/ARCHITECTURE_PRINCIPLES.md) for contribution guidelines.
