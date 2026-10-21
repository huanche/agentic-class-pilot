"""Windows-only development launcher. Never imported by application code or CI.

Keeps the existing production entry points, configuration, schema and workflows
untouched. Reads secrets from ignored local files; never prints their values.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import quote, unquote, urlsplit
from urllib.request import ProxyHandler, build_opener

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
PLATFORM = ROOT / "platform"
TEACHER = ROOT / "teacher_agent"
STUDENT = ROOT / "student_agent"
RUNTIME = ROOT / ".runtime" / "local-dev"
PUBLIC_URL = "http://localhost:8088"
SERVICES = {
    "platform": (8080, "/api/v1/utils/health-check/"),
    "teacher": (3200, "/api/health"),
    "student": (8000, "/api/session/health"),
    "gateway": (8088, "/api/v1/utils/health-check/"),
}
HTTP = build_opener(ProxyHandler({}))


class LocalError(Exception):
    pass


def read_env(path: Path) -> dict[str, str]:
    return {k: v for k, v in dotenv_values(path, encoding="utf-8-sig", interpolate=False).items()
            if v is not None}


def check_database_target(url: str, user: str) -> None:
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme in {"postgres", "postgresql"}
                 and parsed.hostname in {"localhost", "127.0.0.1"}
                 and parsed.port == 55432 and parsed.username == user
                 and parsed.path == "/education")
    except ValueError:
        valid = False
    if not valid:
        raise LocalError(f"{user}: local launcher only accepts localhost:55432/education; refused.")


def configuration() -> dict[str, str]:
    path = PLATFORM / ".env"
    if not path.is_file():
        raise LocalError("Missing platform/.env. Run the documented first-time initialization.")
    config = read_env(path)
    if config.get("ENVIRONMENT", "development") != "development":
        raise LocalError("This launcher requires ENVIRONMENT=development; refused.")
    required = ("DATABASE_URL", "POSTGRES_PASSWORD", "TEACHER_DB_PASSWORD",
                "STUDENT_DATABASE_URL", "TEACHER_SERVICE_KEY", "STUDENT_SERVICE_KEY",
                "STUDENT_TOKEN_SIGNING_KEY", "SECRET_KEY")
    invalid = [k for k in required if not config.get(k, "").strip()
               or config[k].lower().startswith(("change-me", "changethis"))]
    if invalid:
        raise LocalError("Missing, empty or placeholder local configuration: " + ", ".join(invalid))
    check_database_target(config["DATABASE_URL"], "platform")
    check_database_target(config["STUDENT_DATABASE_URL"], "student")
    if unquote(urlsplit(config["DATABASE_URL"]).password or "") != config["POSTGRES_PASSWORD"]:
        raise LocalError("DATABASE_URL and POSTGRES_PASSWORD disagree. Preserve the existing database; repair local credentials.")
    return config


def teacher_database_url(config: dict[str, str]) -> str:
    return "postgresql://teacher:" + quote(config["TEACHER_DB_PASSWORD"], safe="") + "@127.0.0.1:55432/education"


def check_infrastructure(config: dict[str, str]) -> None:
    if config.get("COURSE_OBJECT_STORAGE_MODE") == "minio":
        endpoint = config.get("COURSE_OBJECT_STORAGE_ENDPOINT", "")
        try:
            url = urlsplit(endpoint)
            valid = (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1"}
                     and url.port == 59000 and url.path in {"", "/"})
        except ValueError:
            valid = False
        if not valid:
            raise LocalError("Local MinIO requires http://127.0.0.1:59000; refused nonlocal endpoint.")
        try:
            with HTTP.open(endpoint.rstrip("/") + "/minio/health/live", timeout=4) as response:
                if response.status != 200:
                    raise OSError("not ready")
        except OSError:
            raise LocalError("Local MinIO HTTP health failed (an open TCP port is insufficient). Inspect/restart only the local MinIO container.") from None
        print("[OK] local MinIO HTTP health", flush=True)
    if config.get("SMTP_HOST") in {"localhost", "127.0.0.1"} and config.get("SMTP_PORT") == "51025":
        try:
            with socket.create_connection(("127.0.0.1", 51025), timeout=4) as connection:
                if not connection.recv(1024).startswith(b"220"):
                    raise OSError("not ready")
        except OSError:
            raise LocalError("Local Mailpit SMTP greeting failed. Inspect/restart only the local mail container.") from None
        print("[OK] local Mailpit SMTP greeting (no email sent)", flush=True)


def check_databases(config: dict[str, str]) -> None:
    import psycopg
    for name, url in (("platform", config["DATABASE_URL"]),
                      ("teacher", teacher_database_url(config)),
                      ("student", config["STUDENT_DATABASE_URL"])):
        try:
            with psycopg.connect(url, connect_timeout=4, autocommit=True) as conn:
                conn.execute("SELECT 1")
                if name == "platform":
                    actual = {row[0] for row in conn.execute("SELECT version_num FROM alembic_version")}
        except psycopg.Error:
            raise LocalError(f"{name} database connection failed. Check local role credentials and database readiness; no passwords were changed.") from None
        print(f"[OK] {name} database credentials", flush=True)
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    alembic = Config()
    alembic.set_main_option("script_location", str(PLATFORM / "backend/app/alembic"))
    expected = set(ScriptDirectory.from_config(alembic).get_heads())
    if actual != expected:
        raise LocalError("Local database migrations are not current. Review and run alembic upgrade head in platform/backend first.")
    print("[OK] database migrations are current (no migrations executed)", flush=True)


def environment(config: dict[str, str], service: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(config)
    if service == "student" and (STUDENT / ".env.local").is_file():
        # Personal model settings may vary; shared identity/DB settings must not.
        protected = set(config) | {"PLATFORM_AUTH_URL", "STUDENT_DEMO_MODE"}
        env.update({k: v for k, v in read_env(STUDENT / ".env.local").items() if k not in protected})
    env.update(FRONTEND_HOST=PUBLIC_URL, PLATFORM_PUBLIC_URL=PUBLIC_URL,
               TEACHER_PUBLIC_URL=PUBLIC_URL, STUDENT_PUBLIC_URL=PUBLIC_URL,
               PLATFORM_URL="http://127.0.0.1:8080", PYTHONUTF8="1",
               PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    if service == "teacher":
        env.pop("DATABASE_URL", None)
        env.pop("ACCESS_CODE", None)
        data = TEACHER / ".runtime/data-3200"
        env.update(PLATFORM_AUTH_ENABLED="true", PLATFORM_AUTH_URL="http://127.0.0.1:8080",
                   PLATFORM_SERVICE_KEY=config["TEACHER_SERVICE_KEY"],
                   NEXT_PUBLIC_SAAS_HOST_ORIGIN=PUBLIC_URL, ALLOWED_FRAME_ANCESTORS=PUBLIC_URL,
                   COURSE_STORAGE_MODE="postgres", COURSE_DATABASE_SCHEMA="teacher",
                   COURSE_DATABASE_URL=teacher_database_url(config),
                   COURSE_SPACES_DATA_DIR=str(data / "course-spaces"),
                   CLASSROOMS_DATA_DIR=str(data / "classrooms"),
                   CLASSROOM_JOBS_DATA_DIR=str(data / "classroom-jobs"))
        env.setdefault("NODE_OPTIONS", "--max-old-space-size=8192")
        env["COURSE_OBJECT_STORAGE_SECRET_KEY"] = (config.get("COURSE_OBJECT_STORAGE_SECRET_KEY")
            or config.get("MINIO_ROOT_PASSWORD") or config["TEACHER_DB_PASSWORD"])
    elif service == "student":
        env.update(PLATFORM_AUTH_URL="http://127.0.0.1:8080/api/v1", STUDENT_DEMO_MODE="false")
    return env


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    if subprocess.call(command, cwd=cwd, env=env) != 0:
        raise LocalError(f"Command failed in {cwd.relative_to(ROOT)}. See the output above.")


def check_dependencies() -> None:
    for path in (STUDENT / ".venv/Scripts/python.exe",
                 TEACHER / "node_modules/next/dist/bin/next",
                 STUDENT / "frontend/node_modules/next/dist/bin/next",
                 PLATFORM / "node_modules/vite/bin/vite.js"):
        if not path.is_file():
            raise LocalError(f"Missing dependency: {path.relative_to(ROOT)}. Follow first-time installation instructions.")
    if not shutil.which("node"):
        raise LocalError("Node.js is not available on PATH.")


def fingerprint(directory: Path, names: tuple[str, ...], directories: tuple[str, ...] = ("src",)) -> str:
    files = [directory / name for name in names if (directory / name).is_file()]
    for name in directories:
        files.extend(p for p in (directory / name).rglob("*") if p.is_file())
    combined = hashlib.sha256()
    for path in sorted(files, key=lambda p: p.relative_to(directory).as_posix()):
        combined.update(path.relative_to(directory).as_posix().encode())
        combined.update(b"\0")
        combined.update(hashlib.sha256(path.read_bytes()).digest())
    return combined.hexdigest()


def prepare_frontends(skip_build: bool) -> None:
    node = shutil.which("node")
    frontend = PLATFORM / "frontend"
    expected = fingerprint(frontend, ("package.json", "vite.config.ts", "tsconfig.json", "index.html",
        "../bun.lock", "../package.json"), ("src", "public"))
    stamp = RUNTIME / "platform-frontend.fingerprint"
    if (not (PLATFORM / "backend/app/frontend/index.html").is_file()
            or not stamp.is_file() or stamp.read_text().strip() != expected):
        if skip_build:
            raise LocalError("Platform frontend freshness is unverified; run without --skip-build.")
        run([node, str(PLATFORM / "node_modules/vite/bin/vite.js"), "build"], frontend)
        stamp.write_text(expected, encoding="utf-8")
    frontend = STUDENT / "frontend"
    expected = fingerprint(frontend, ("package.json", "package-lock.json", "next.config.mjs"))
    served = STUDENT / "apps/static/app"
    stamp = served / ".build-fingerprint"
    if not (served / "index.html").is_file() or not stamp.is_file() or stamp.read_text().strip() != expected:
        if skip_build:
            raise LocalError("Student frontend is stale or missing; run without --skip-build.")
        run([node, str(frontend / "node_modules/next/dist/bin/next"), "build"], frontend)
        run([node, str(frontend / "scripts/write-build-fingerprint.mjs")], frontend)
        if (frontend / "out/.build-fingerprint").read_text().strip() != expected:
            raise LocalError("Student build fingerprint mismatch; not publishing stale files.")
        # Keep the previous served bundle recoverable, including its fingerprint.
        if served.exists():
            served.rename(RUNTIME / f"student-frontend-backup-{time.time_ns()}")
        shutil.copytree(frontend / "out", served)
    print("[OK] current platform and student frontends", flush=True)


def healthy(name: str) -> bool:
    port, path = SERVICES[name]
    try:
        with HTTP.open(f"http://127.0.0.1:{port}{path}", timeout=3) as response:
            return response.status == 200
    except (OSError, ValueError):
        return False


def listening(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def owned_worker(pid: int, service: str) -> bool:
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command",
        f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine"],
        capture_output=True, text=True)
    return str(SCRIPT).lower() in result.stdout.lower() and f"--service {service}" in result.stdout


def stop_services() -> None:
    state_file = RUNTIME / "processes.json"
    state = json.loads(state_file.read_text()) if state_file.is_file() else {}
    for name, record in list(state.items())[::-1]:
        if owned_worker(record["pid"], name):
            result = subprocess.run(["taskkill", "/PID", str(record["pid"]), "/T", "/F"],
                                    capture_output=True)
            if result.returncode:
                raise LocalError(f"Could not stop this checkout's {name} worker.")
            print(f"[OK] stopped this checkout's {name}", flush=True)
        state.pop(name)
        state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")


def start_services() -> None:
    state_file = RUNTIME / "processes.json"
    state = json.loads(state_file.read_text()) if state_file.is_file() else {}
    for name, (port, _) in SERVICES.items():
        previous = state.get(name, {})
        if previous and owned_worker(previous["pid"], name):
            if healthy(name):
                print(f"[OK] reusing this checkout's {name} on {port}", flush=True)
                continue
            raise LocalError(f"Existing {name} worker is unhealthy; inspect {previous['stderr']} before restarting.")
        if listening(port):
            raise LocalError(f"Port {port} is occupied by an unmanaged process. Refusing to reuse or stop it.")
        label = f"{name}-{time.time_ns()}"
        stdout, stderr = RUNTIME / f"{label}.stdout.log", RUNTIME / f"{label}.stderr.log"
        with stdout.open("w", encoding="utf-8") as out, stderr.open("w", encoding="utf-8") as err:
            process = subprocess.Popen([sys.executable, str(SCRIPT), "--service", name],
                cwd=ROOT, stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
        state[name] = {"pid": process.pid, "stdout": str(stdout), "stderr": str(stderr)}
        state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
        deadline = time.monotonic() + (180 if name == "teacher" else 60)
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise LocalError(f"{name} exited ({process.returncode}). Logs: {stdout} and {stderr}")
            if healthy(name):
                print(f"[OK] {name} ready on {port}", flush=True)
                break
            time.sleep(1)
        else:
            raise LocalError(f"{name} readiness timed out. Logs: {stdout} and {stderr}")


def worker(name: str, config: dict[str, str]) -> None:
    env = environment(config, name)
    if name == "platform":
        command, cwd = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8080"], PLATFORM / "backend"
    elif name == "teacher":
        command, cwd = [shutil.which("node"), str(TEACHER / "node_modules/next/dist/bin/next"), "dev", "--hostname", "127.0.0.1", "--port", "3200"], TEACHER
    elif name == "student":
        command, cwd = [str(STUDENT / ".venv/Scripts/python.exe"), "apps/start.py", "--no-browser", "--host", "127.0.0.1", "--port", "8000"], STUDENT
    else:
        import yaml
        routing = yaml.safe_load((ROOT / "contracts/routing.yaml").read_text(encoding="utf-8"))
        env["LOCAL_GATEWAY_ROUTES"] = json.dumps(routing["environments"]["local-extended"]["routes"])
        command, cwd = [shutil.which("node"), str(ROOT / "scripts/local-gateway.mjs")], ROOT
    run(command, cwd, env)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--skip-infrastructure", action="store_true")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--stop", action="store_true", help="stop only workers owned by this checkout; keep Docker and data")
    parser.add_argument("--service", choices=SERVICES)
    args = parser.parse_args()
    if sys.platform != "win32" or os.environ.get("CI"):
        raise LocalError("Windows local development only; refuses CI and production use.")
    if args.stop:
        stop_services()
        return 0
    config = configuration()
    if args.service:
        worker(args.service, config)
        return 0
    check_dependencies()
    if not args.check and not args.skip_infrastructure:
        # Do not recreate an already running infrastructure stack or rotate its credentials.
        if not all(listening(port) for port in (55432, 59000, 51025)):
            run(["docker", "compose", "-f", "compose.local.yml", "up", "-d", "--wait",
                 "database", "minio", "mail"], PLATFORM, environment(config, "platform"))
    check_databases(config)
    check_infrastructure(config)
    if args.check:
        print("[OK] local configuration and dependencies; no services started or files changed.")
        return 0
    RUNTIME.mkdir(parents=True, exist_ok=True)
    prepare_frontends(args.skip_build)
    start_services()
    print(f"Ready: {PUBLIC_URL}\nLogs: {RUNTIME}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LocalError as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        raise SystemExit(1)
