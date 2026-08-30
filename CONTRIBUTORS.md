# Contributors

FraiseQL is maintained by [@evoludigit](https://github.com/evoludigit).

This file records people outside the maintainer group whose work has shaped the
project. It is not a list of everyone who has opened a pull request — it names
contributions that changed what shipped, including diagnoses that were correct
first and were then built on.

## Contributions

### [@mikemikimike](https://github.com/mikemikimike)

Identified the root cause behind [#505](https://github.com/fraiseql/fraiseql-python/issues/505):
all six vector distance operators rendered a bare distance expression, which is
a `double precision` and not a predicate, so PostgreSQL rejected every WHERE
clause containing one with `argument of WHERE must be type boolean`. The fix —
wrap the distance in the requested comparison inside the operator registry — is
the approach [#511](https://github.com/fraiseql/fraiseql-python/pull/511)
shipped, filed in [#509](https://github.com/fraiseql/fraiseql-python/pull/509)
an hour and a half before that PR was opened.

### [@Joemon24](https://github.com/Joemon24)

Produced the compile fixes for the Rust benchmark targets in
[#491](https://github.com/fraiseql/fraiseql-python/pull/491), answering
[#471](https://github.com/fraiseql/fraiseql-python/issues/471): the benches had
drifted past the API they call, and no CI job compiled them. The source changes
that landed in [#500](https://github.com/fraiseql/fraiseql-python/pull/500) two
hours later are equivalent to theirs.

## Adding to this file

Maintainers add entries when a contribution lands, whether it merged as its own
pull request or was folded into another. If your work shaped a change and you
are not listed, say so on the pull request or open an issue — the omission is an
oversight, not a judgement.
