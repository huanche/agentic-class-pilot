"""Opt-in PostgreSQL tests create their own database on a dedicated loopback cluster."""
import ast
import os
from pathlib import Path
import sys
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def without_trace(value):
    """Keep legacy behavior assertions exact while P3 adds separately tested trace metadata."""
    if isinstance(value, list):
        return [without_trace(item) for item in value]
    if isinstance(value, dict):
        added = {"messageId", "episodeId", "taskId", "createdAt", "recordOrigin", "relatedTaskIds",
                 "recordSchemaVersion", "evidenceSummary", "observationIds", "evidenceLimitations"}
        return {key: without_trace(item) for key, item in value.items() if key not in added}
    return value


@pytest.fixture(scope="session")
def isolated_database_url():
    url = os.environ.get("STUDENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set STUDENT_TEST_DATABASE_URL to the disposable student_p2_test loopback cluster")
    import psycopg
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from psycopg import sql
    info = conninfo_to_dict(url)
    # Never consume STUDENT_DATABASE_URL, DATABASE_URL or a developer .env for tests.
    if (info.get("host") not in {"127.0.0.1", "localhost"}
            or info.get("user") != "student_p2_test" or info.get("dbname") != "postgres"):
        pytest.fail("PostgreSQL tests require user=student_p2_test, loopback host, dbname=postgres")
    name = "student_p2_test_" + uuid4().hex
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    target = make_conninfo(url, dbname=name)
    root = Path(__file__).resolve().parents[3]
    migrations = root / "platform/backend/app/alembic/versions"
    with psycopg.connect(target) as connection:
        connection.execute("CREATE SCHEMA student")
        for filename in ("final05_student_schema.py", "pub10_published_lesson_knowledge.py", "cmd11_reliable_student_commands.py", "rec12_student_learning_records.py"):
            tree = ast.parse((migrations / filename).read_text(encoding="utf-8"))
            statements = next((ast.literal_eval(node.value) for node in tree.body
                              if isinstance(node, ast.Assign) and any(
                                  isinstance(t, ast.Name) and t.id == "STATEMENTS" for t in node.targets)), None)
            if statements is None:
                upgrade = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade")
                statements = [ast.literal_eval(n.value.args[0]) for n in upgrade.body if isinstance(n, ast.Expr)
                              and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute)
                              and n.value.func.attr == "execute"]
                statements = [sql for sql in statements if not sql.startswith("GRANT")]
            for statement in statements:
                connection.execute(statement)
    try:
        yield target
    finally:
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def pg(isolated_database_url, monkeypatch):
    import psycopg
    monkeypatch.setenv("STUDENT_DATABASE_URL", isolated_database_url)
    monkeypatch.setenv("STUDENT_FRESH_SESSION_MODE", "1")
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "isolated-command-test-key")
    monkeypatch.setenv("STUDENT_AGENT_RECALL_ROUNDS", "8")
    monkeypatch.setenv("STUDENT_AGENT_REINFORCE_ROUNDS", "4")
    with psycopg.connect(isolated_database_url) as connection:
        tables = connection.execute("SELECT tablename FROM pg_tables WHERE schemaname='student'").fetchall()
        from psycopg import sql
        connection.execute(sql.SQL("TRUNCATE {} RESTART IDENTITY").format(sql.SQL(",").join(
            sql.Identifier("student", row[0]) for row in tables)))
    from backend.infrastructure import database
    return database._db
