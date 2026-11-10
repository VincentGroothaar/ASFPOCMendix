"""Store requisitions and hand out requisition numbers, in Postgres schema `mock_pr`.

The mock shares the database with the Cockpit app but keeps its own schema (D-27). The number
comes from a Postgres sequence, so numbers stay unique across restarts and parallel requests.
"""

import json
import re

import psycopg
from psycopg import sql

DEFAULT_SCHEMA = "mock_pr"
# SAP's internal numbering for purchase requisitions starts at 10000000 (8 digits, no padding).
FIRST_NUMBER = 10000000
SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


class RequisitionStore:
    """Read and write requisitions in one Postgres schema."""

    def __init__(self, database_url: str, schema: str = DEFAULT_SCHEMA) -> None:
        if not SCHEMA_NAME.match(schema):
            raise ValueError("The schema name may contain only lower-case letters, digits and _.")
        self.database_url = database_url
        self.schema = schema

    def create_tables(self) -> None:
        """Create the schema, the number sequence and the table if they do not exist yet."""
        statements = [
            "CREATE SCHEMA IF NOT EXISTS {schema}",
            "CREATE SEQUENCE IF NOT EXISTS {schema}.requisition_number START {first}",
            """CREATE TABLE IF NOT EXISTS {schema}.requisition (
                number text PRIMARY KEY,
                created_at timestamptz NOT NULL DEFAULT now(),
                body jsonb NOT NULL
            )""",
        ]
        with self._connect() as connection:
            for statement in statements:
                connection.execute(self._sql(statement))

    def next_number(self) -> str:
        """Return a new, unique requisition number, e.g. "10000000"."""
        with self._connect() as connection:
            row = connection.execute(
                self._sql("SELECT nextval('{schema}.requisition_number')")
            ).fetchone()
        return str(row[0])

    def save(self, number: str, body: dict) -> None:
        """Store a requisition's OData body under its number."""
        with self._connect() as connection:
            connection.execute(
                self._sql("INSERT INTO {schema}.requisition (number, body) VALUES (%s, %s)"),
                (number, json.dumps(body)),
            )

    def load(self, number: str) -> dict | None:
        """Return the stored body of a requisition, or None if the number is unknown."""
        with self._connect() as connection:
            row = connection.execute(
                self._sql("SELECT body FROM {schema}.requisition WHERE number = %s"), (number,)
            ).fetchone()
        return None if row is None else row[0]

    def drop_schema(self) -> None:
        """Remove the schema with everything in it. Used by the tests only."""
        with self._connect() as connection:
            connection.execute(self._sql("DROP SCHEMA IF EXISTS {schema} CASCADE"))

    def _connect(self) -> psycopg.Connection:
        # A short-lived connection per call is enough for a mock and keeps the code simple.
        return psycopg.connect(self.database_url)

    def _sql(self, template: str) -> sql.Composed:
        """Fill in the schema name (quoted safely) and the first number."""
        return sql.SQL(template).format(
            schema=sql.Identifier(self.schema), first=sql.Literal(FIRST_NUMBER)
        )
