"""Protect the physical Module seams, pure dependency closure and deployment entry points."""
import ast
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCES = {"backend." + ".".join(p.relative_to(ROOT / "backend").with_suffix("").parts): p
           for p in (ROOT / "backend").rglob("*.py")
           if "tests" not in p.parts and p.name != "__init__.py"}


def dependencies(module, *, eager=False):
    tree = ast.parse(SOURCES[module].read_text(encoding="utf-8"))
    def walk(node):
        if eager and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("backend"):
            for alias in node.names:
                full = node.module + "." + alias.name
                target = full if full in SOURCES else node.module
                if target in SOURCES:
                    yield target
        for child in ast.iter_child_nodes(node):
            yield from walk(child)
    return set(walk(tree))


def test_production_and_subprocess_imports_use_the_new_homes():
    assert not list((ROOT / "agent").rglob("*.py")), "Old Agent source implementations must be removed"
    obsolete = {"learning_session", "command_runtime", "platform_access", "errors", "teaching"}
    for p in [*(ROOT / "backend").rglob("*.py"), *(ROOT / "apps").glob("*.py")]:
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("agent"), p
                if node.module == "backend":
                    assert not obsolete.intersection(a.name for a in node.names), p
            elif isinstance(node, ast.Import):
                assert not any(a.name == "agent" or a.name.startswith("agent.") for a in node.names), p
            elif p.name != Path(__file__).name and isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert "from agent import" not in node.value and "from agent." not in node.value, p


def test_evidence_and_content_definitions_have_no_transitive_io_or_executor_dependency():
    pure = {"backend.contracts", "backend.content.context", "backend.content.lesson_content", "backend.content.knowledge_schema",
            "backend.content.prompts", "backend.teaching.dynamic_state", "backend.teaching.postclass_state",
            "backend.teaching.progression", "backend.teaching.prompts", "backend.evidence.records",
            "backend.evidence.feedback", "backend.teaching.typed_state"}
    for module in pure:
        pending, seen = [module], set()
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            assert current in pure, (module, current)
            pending.extend(dependencies(current))


def test_eager_module_dependencies_are_acyclic_and_transport_stays_at_the_entry():
    done, visiting = set(), []
    def visit(module):
        assert module not in visiting, visiting + [module]
        if module in done:
            return
        visiting.append(module)
        for target in dependencies(module, eager=True):
            visit(target)
        visiting.pop(); done.add(module)
    for module, path in SOURCES.items():
        visit(module)
        if module != "backend.main":
            assert "backend.main" not in dependencies(module), module
        if module not in {"backend.main", "backend.internal_platform"}:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            assert not any(isinstance(n, ast.ImportFrom) and (n.module or "").startswith("fastapi")
                           for n in ast.walk(tree)), path


def test_cold_imports_legacy_launchers_health_static_location_and_cli_help():
    # Exercise real startup imports in a fresh process without reading local platform credentials.
    script = '''
import importlib, pathlib, runpy, sys, os
root = pathlib.Path(sys.argv[1])
os.environ.update(PLATFORM_AUTH_URL='https://platform.example.test/api/v1', STUDENT_SERVICE_KEY='layout-test-key', PLATFORM_TO_STUDENT_KEY='layout-forward-key',
                  STUDENT_AGENT_API_KEY='layout-model-test-key', STUDENT_DATABASE_URL='postgresql://unused@127.0.0.1/unused')
original = pathlib.Path.is_file
pathlib.Path.is_file = lambda p: False if p.name in {'.env', '.env.local'} else original(p)
for path in (root / 'backend').rglob('*.py'):
    if 'tests' not in path.parts and path.name != '__init__.py':
        importlib.import_module('backend.' + '.'.join(path.relative_to(root / 'backend').with_suffix('').parts))
from backend.main import app, OUT
from apps.server import app as legacy
from apps.start import app as launcher
assert app is legacy is launcher
assert OUT.resolve() == (root / 'frontend/out').resolve()
from fastapi.testclient import TestClient
assert TestClient(app).get('/api/session/health').status_code == 200
if OUT.is_dir():
    assert TestClient(app).get('/app/').status_code == 200
    assert TestClient(app).get('/app/').headers['cache-control'] == 'no-cache'
assert '/api/session/{sid}/commands' in app.openapi()['paths']
sys.argv = ['apps/start.py', '--help']
runpy.run_path(str(root / 'apps/start.py'), run_name='__main__')
'''
    result = subprocess.run([sys.executable, "-c", script, str(ROOT)],
        env=dict(os.environ, PYTHONPATH=str(ROOT)), capture_output=True, timeout=20,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert b"--port" in result.stdout and b"--no-browser" in result.stdout
