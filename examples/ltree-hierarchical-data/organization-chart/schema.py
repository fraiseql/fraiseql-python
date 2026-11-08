"""FraiseQL Organization Chart - ltree hierarchies.

Run setup.sql on a database, then:

    DATABASE_URL=postgresql://localhost/org_chart python schema.py
"""

import os
from datetime import date

import fraiseql
from fraiseql.db import register_type_for_view
from fraiseql.fastapi import create_fraiseql_app
from fraiseql.types import ID, LTree


@fraiseql.type(sql_source="v_employee")
class Employee:
    """Employee in the organization hierarchy."""

    id: ID
    name: str
    title: str
    department: str
    org_path: LTree  # The chain of managers down to this employee
    level: int  # 1 for the CEO, 2 for their direct reports, ...
    hire_date: date


# v_employee exposes org_path as a real ltree column (and its level) next to
# data: filters on it then use PostgreSQL's ltree operators and the GiST index.
register_type_for_view(
    "v_employee",
    Employee,
    table_columns={"id", "org_path", "level", "department", "data"},
    has_jsonb_data=True,
)


@fraiseql.query
async def employees(
    info, where=None, order_by=None, limit: int | None = None, offset: int | None = None
) -> list[Employee]:
    """List employees, with fraiseql's filters, including ltree ones on orgPath."""
    db = info.context["db"]
    return await db.find(
        "v_employee",
        "employees",
        info,
        where=where,
        order_by=order_by,
        limit=limit,
        offset=offset,
    )


@fraiseql.query
async def employee(info, id: ID) -> Employee | None:
    """Get an employee by ID."""
    db = info.context["db"]
    return await db.find_one("v_employee", "employee", info, mandatory_filters={"id": id})


@fraiseql.query
async def reports(info, org_path: str, direct_only: bool = False) -> list[Employee]:
    """Employees under the one at org_path: everyone, or only direct reports."""
    level = len(org_path.split("."))
    below = {"eq": level + 1} if direct_only else {"gt": level}
    db = info.context["db"]
    return await db.find(
        "v_employee",
        "reports",
        info,
        where={"org_path": {"descendant_of": org_path}, "level": below},
        order_by=[{"org_path": "asc"}],
    )


@fraiseql.query
async def chain_of_command(info, org_path: str) -> list[Employee]:
    """The managers above the employee at org_path, from the top down."""
    level = len(org_path.split("."))
    db = info.context["db"]
    return await db.find(
        "v_employee",
        "chainOfCommand",
        info,
        where={"org_path": {"ancestor_of": org_path}, "level": {"lt": level}},
        order_by=[{"org_path": "asc"}],
    )


app = create_fraiseql_app(
    database_url=os.getenv("DATABASE_URL", "postgresql://localhost/org_chart"),
    types=[Employee],
    queries=[employees, employee, reports, chain_of_command],
    title="Organization Chart API",
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
