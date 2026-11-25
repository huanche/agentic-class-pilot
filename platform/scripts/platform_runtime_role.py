"""Prepare or check a public-only platform runtime role.

Run migrations with MIGRATION_DATABASE_URL. Pass that URL and a separately
generated PLATFORM_RUNTIME_DB_PASSWORD in the environment; never in arguments.
The script refuses a database whose name differs from --database-name.
"""
from __future__ import annotations

import argparse
import os
from urllib.parse import quote, urlsplit, urlunsplit

import psycopg
from psycopg import sql

ROLE = "platform_runtime"


def runtime_url(admin_url: str, password: str) -> str:
    parts = urlsplit(admin_url)
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    port = f":{parts.port}" if parts.port else ""
    return urlunsplit(parts._replace(netloc=f"{ROLE}:{quote(password, safe='')}@{host}{port}"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-name", required=True)
    parser.add_argument("--apply", action="store_true", help="create/grant the role; default is read-only verification")
    args = parser.parse_args()
    admin_url = os.environ.get("MIGRATION_DATABASE_URL", "")
    password = os.environ.get("PLATFORM_RUNTIME_DB_PASSWORD", "")
    if not admin_url or not password:
        parser.error("MIGRATION_DATABASE_URL and PLATFORM_RUNTIME_DB_PASSWORD are required")
    parsed = urlsplit(admin_url)
    if parsed.scheme not in {"postgres", "postgresql", "postgresql+psycopg"} or parsed.path != f"/{args.database_name}":
        parser.error("migration URL must be PostgreSQL and match --database-name exactly")
    if args.database_name in {"postgres", "template0", "template1"}:
        parser.error("refusing a PostgreSQL maintenance database")

    with psycopg.connect(admin_url.replace("+psycopg", ""), connect_timeout=5, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), current_user")
            actual_db, migrator = cur.fetchone()
            if actual_db != args.database_name:
                raise RuntimeError("connected database does not match --database-name")
            if args.apply:
                cur.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (ROLE,))
                if not cur.fetchone():
                    cur.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(ROLE)))
                cur.execute(sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(ROLE), sql.Literal(password)))
                cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(actual_db), sql.Identifier(ROLE)))
                cur.execute(sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(sql.Identifier(ROLE)))
                cur.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}").format(sql.Identifier(ROLE)))
                cur.execute(sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(sql.Identifier(ROLE)))
                cur.execute(sql.SQL(
                    "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
                    "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}"
                ).format(sql.Identifier(migrator), sql.Identifier(ROLE)))
                cur.execute(sql.SQL(
                    "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
                    "GRANT USAGE, SELECT ON SEQUENCES TO {}"
                ).format(sql.Identifier(migrator), sql.Identifier(ROLE)))
                for schema in ("teacher", "student"):
                    cur.execute(sql.SQL("REVOKE ALL ON SCHEMA {} FROM {}").format(
                        sql.Identifier(schema), sql.Identifier(ROLE)))
                print(f"role {ROLE} prepared for {actual_db}")

    with psycopg.connect(runtime_url(admin_url.replace("+psycopg", ""), password), connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = current_user")
            if cur.fetchone() != (False, False, False):
                raise RuntimeError(f"{ROLE} must not be a privileged database role")
            cur.execute("SELECT 1 FROM public.course LIMIT 1")
            cur.execute("""
                SELECT n.nspname, c.relname
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname IN ('teacher', 'student')
                  AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
                  AND (
                    has_table_privilege(c.oid, 'SELECT')
                    OR has_table_privilege(c.oid, 'INSERT')
                    OR has_table_privilege(c.oid, 'UPDATE')
                    OR has_table_privilege(c.oid, 'DELETE')
                  )
                LIMIT 1
            """)
            accessible = cur.fetchone()
            if accessible:
                raise RuntimeError(f"{ROLE} can access {accessible[0]}.{accessible[1]}; refusing to pass")
    print(f"role {ROLE} can read public and cannot read teacher/student in {args.database_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
