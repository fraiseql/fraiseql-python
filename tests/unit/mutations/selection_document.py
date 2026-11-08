"""Read the mutation selection document back as field names, for extraction tests.

The resolver sends Rust one selection document (``_response_selections``, format 2):
fields as ``{"name", "alias", "selections"?}`` entries, keyed by response key. Tests
written against the earlier helpers check *which* fields a query selects (fragment
expansion, merging, ``__typename``, abstract fields), not the document's shape. These
functions give them that view of the new document, keyed by name as graphql-core
reads fields:

- ``selected_field_names(info, type_name)``: the names selected on the result type
  ``type_name``, without ``__typename``; None when there are none.
- ``entity_selection(info, type_name, field_name)``: the selection of one field of
  the result type, as ``{"fields": [names], "__type"?: name, "<name>": {...}}``; None
  when the field isn't selected or has no sub-selection.

``info_for(query)`` builds the info the resolver gets for a query's first root
field, without a schema.
"""

from types import SimpleNamespace
from typing import Any

from graphql import FragmentDefinitionNode, OperationDefinitionNode, parse

from fraiseql.mutations.mutation_decorator import _response_selections

UNFILTERED = '{"format": 2, "success": null, "error": null}'


def info_for(query: str, schema: Any = None) -> SimpleNamespace:
    definitions = parse(query).definitions
    operation = next(d for d in definitions if isinstance(d, OperationDefinitionNode))
    root = operation.selection_set.selections[0]
    return SimpleNamespace(
        schema=schema,
        field_nodes=[root],
        fragments={d.name.value: d for d in definitions if isinstance(d, FragmentDefinitionNode)},
        path=SimpleNamespace(key=root.alias.value if root.alias else root.name.value),
    )


def _result_selection(info: Any, type_name: str) -> dict[str, Any]:
    return _response_selections(info, type_name, f"{type_name}__unused", by_alias=False)["success"]


def selected_field_names(info: Any, type_name: str) -> list[str] | None:
    names = [
        field["name"]
        for field in _result_selection(info, type_name)["fields"]
        if field["name"] != "__typename"
    ]
    return names or None


def _by_name(selection: dict[str, Any]) -> dict[str, Any] | None:
    named: dict[str, Any] = {"fields": [field["name"] for field in selection["fields"]]}
    if "__type" in selection:
        named["__type"] = selection["__type"]
    for field in selection["fields"]:
        sub_selection = field.get("selections")
        if sub_selection is not None and (nested := _by_name(sub_selection)) is not None:
            named[field["name"]] = nested
    return named if named["fields"] else None


def entity_selection(info: Any, type_name: str, field_name: str) -> dict[str, Any] | None:
    for field in _result_selection(info, type_name)["fields"]:
        if field["name"] == field_name and "selections" in field:
            return _by_name(field["selections"])
    return None


def _from_names(names: list[str], nested: dict[str, Any]) -> list[dict[str, Any]]:
    fields = []
    for name in names:
        field: dict[str, Any] = {"name": name, "alias": name}
        if name in nested:
            field["selections"] = _from_named(nested[name])
        fields.append(field)
    return fields


def _from_named(selection: dict[str, Any]) -> dict[str, Any]:
    converted: dict[str, Any] = {"fields": _from_names(selection["fields"], selection)}
    if "__type" in selection:
        converted["__type"] = selection["__type"]
    return converted


def legacy_document(
    success_fields: list[str] | None = None,
    error_fields: list[str] | None = None,
    entity_field: str | None = None,
    entity_selections: str | dict[str, Any] | None = None,
) -> str:
    """A selection document from the arguments build_mutation_response took before it.

    Field name lists become fields keyed by name; a field without a sub-selection is
    copied whole, as before. None stays "unfiltered". The entity's selection, in the
    earlier ``{"fields": [names], "<name>": {...}}`` form, becomes the sub-selection of
    entity_field, which must then be in success_fields.
    """
    import json

    nested: dict[str, Any] = {}
    if entity_selections is not None:
        if isinstance(entity_selections, str):
            entity_selections = json.loads(entity_selections)
        if success_fields is None or entity_field not in success_fields:
            raise ValueError("an entity selection needs entity_field in success_fields")
        nested[entity_field] = entity_selections

    def selection(names: list[str] | None) -> dict[str, Any] | None:
        return None if names is None else {"fields": _from_names(names, nested)}

    return json.dumps(
        {"format": 2, "success": selection(success_fields), "error": selection(error_fields)}
    )
