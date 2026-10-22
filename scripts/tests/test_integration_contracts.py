"""Contract gates and isolated provider functions; no app import, DB or network."""
import ast
import base64
import copy
import fnmatch
import hashlib
import hmac
import importlib.util
import json
import logging
import re
from pathlib import Path
import secrets
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import uuid

import yaml
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("integration_gate", ROOT / "scripts/check_integration_contracts.py")
gate = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = gate
spec.loader.exec_module(gate)
ROUTES, _ = gate.provider_routes(ROOT)
TEACHER_SPEC = ROOT / "contracts/internal-teacher-api.yaml"
STUDENT_SPEC = ROOT / "contracts/internal-student-api.yaml"


def operation(path, endpoint, method):
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    return spec, spec["paths"][endpoint][method]


def load_functions(path, names, namespace):
    """Execute only selected real function bodies with explicit test adapters.

    This deliberately does not execute module globals, decorators, settings
    loading, session factories, network clients, or application lifespan.
    """
    source = ast.parse(path.read_text(encoding="utf-8"))
    nodes = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
    for node in source.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            node = copy.deepcopy(node)
            node.decorator_list = []
            nodes.append(node)
    if len(nodes) != len(names) + 1:
        raise AssertionError("Selected provider function disappeared")
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    exec(compile(module, str(path), "exec"), namespace)
    return namespace


class ContractGateTests(unittest.TestCase):
    def test_repository_contracts_match_current_provider_declarations(self):
        self.assertEqual(gate.check(ROOT), [])

    def test_method_change_is_detected_even_if_path_string_still_exists(self):
        source = ROOT / "platform/backend/app/api"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "platform/backend/app/api"
            (target / "routes").mkdir(parents=True)
            (target / "main.py").write_text((source / "main.py").read_text(encoding="utf-8"), encoding="utf-8")
            for name in gate.SOURCES:
                text = (source / "routes" / f"{name}.py").read_text(encoding="utf-8")
                if name == "student_bridge":
                    text = text.replace('@router.post("/internal/student/authorize")', '@router.get("/internal/student/authorize")')
                (target / "routes" / f"{name}.py").write_text(text, encoding="utf-8")
            routes, _ = gate.provider_routes(root)
        self.assertNotIn(("post", "/internal/student/authorize"), routes)
        self.assertIn(("get", "/internal/student/authorize"), routes)

    def test_header_must_exist_on_this_handler_not_elsewhere_in_module(self):
        endpoint = "/internal/student/learning-context"
        spec, op = operation(STUDENT_SPEC, endpoint, "post")
        spec["components"]["securitySchemes"]["studentServiceKey"]["name"] = "X-Teacher-Service-Key"
        issues = gate.compare_operation(ROUTES["post", endpoint], op, spec, STUDENT_SPEC)
        self.assertTrue(any("not declared on this handler" in issue for issue in issues))

    def test_missing_security_declaration_fails(self):
        endpoint = "/internal/student/authorize"
        spec, op = operation(STUDENT_SPEC, endpoint, "post")
        del op["security"]
        self.assertTrue(gate.compare_operation(ROUTES["post", endpoint], op, spec, STUDENT_SPEC))

    def test_required_body_and_type_drift_are_detected(self):
        endpoint = "/internal/teacher/courses"
        spec, op = operation(TEACHER_SPEC, endpoint, "post")
        body = op["requestBody"]["content"]["application/json"]["schema"]
        body["required"].remove("teacher_id")
        body["properties"]["title"]["type"] = "integer"
        issues = gate.compare_operation(ROUTES["post", endpoint], op, spec, TEACHER_SPEC)
        self.assertTrue(any("required fields differ" in issue for issue in issues))
        self.assertTrue(any("title.type differs" in issue for issue in issues))

    def test_old_incorrect_student_response_contract_is_rejected(self):
        endpoint = "/internal/student/authorize"
        spec, op = operation(STUDENT_SPEC, endpoint, "post")
        op["responses"]["200"]["content"]["application/json"]["schema"]["required"] = ["userId", "role", "isAdmin"]
        issues = gate.compare_operation(ROUTES["post", endpoint], op, spec, STUDENT_SPEC)
        self.assertTrue(any("does not always return" in issue for issue in issues))

    def test_shared_model_configuration_is_declared_in_both_specs(self):
        endpoint = "/internal/user/{user_id}/model-config"
        for path in (STUDENT_SPEC, TEACHER_SPEC):
            spec, op = operation(path, endpoint, "get")
            self.assertEqual(gate.compare_operation(ROUTES["get", endpoint], op, spec, path), [])

    def test_remote_schema_references_are_rejected_without_network(self):
        self.assertTrue(gate.reference_problems({"$ref": "https://example.invalid/schema"}, ROOT / "contracts"))
        self.assertTrue(gate.reference_problems({"$ref": "./../platform/.env"}, ROOT / "contracts"))
        self.assertEqual(gate.reference_problems({"$ref": "#/$defs/classroom"}, ROOT / "contracts"), [])

    def test_this_batch_does_not_trigger_existing_production_deploy_workflows(self):
        changed = ("contracts/internal-teacher-api.yaml", "contracts/internal-student-api.yaml",
                   "contracts/learning-context.schema.json", "contracts/requirements-dev.txt",
                   "contracts/README.md", "scripts/check_integration_contracts.py",
                   "scripts/tests/test_integration_contracts.py", ".github/workflows/integration-contracts.yml",
                   "docs/decoupling-progress.md")
        checked = 0
        for path in (ROOT / ".github/workflows").glob("*-deploy.yml"):
            workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
            push = (workflow.get("on", workflow.get(True)) or {}).get("push")
            if not isinstance(push, dict) or "main" not in push.get("branches", []):
                continue
            checked += 1
            self.assertTrue(push.get("paths"), f"{path.name}: missing deployment path filter")
            for filename in changed:
                self.assertFalse(any(fnmatch.fnmatchcase(filename, pattern) for pattern in push["paths"]),
                                 f"{filename} triggers {path.name}")
        self.assertGreaterEqual(checked, 3)


class ProviderPayloadTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads((ROOT / "contracts/learning-context.schema.json").read_text())
        self.validator = Draft202012Validator(self.schema, format_checker=FormatChecker())
        self.payload = json.loads((ROOT / "student_agent/tests/fixtures/platform-learning-context-v1.json").read_text(encoding="utf-8"))

    def test_legacy_absent_lessons_and_explicit_empty_catalog_remain_distinct(self):
        self.validator.validate(self.payload)
        explicit_empty = dict(self.payload, lessons=[], classroom=None)
        self.validator.validate(explicit_empty)
        self.assertNotIn("lessons", self.payload)
        self.assertEqual(explicit_empty["lessons"], [])

    def test_future_additive_fields_are_accepted_but_wrong_version_is_not(self):
        self.validator.validate(dict(self.payload, futureOptionalField={"anything": True}))
        with self.assertRaises(ValidationError):
            self.validator.validate(dict(self.payload, schemaVersion=2))
        broken = copy.deepcopy(self.payload)
        del broken["publication"]["version"]
        with self.assertRaises(ValidationError):
            self.validator.validate(broken)

    def test_real_provider_authorize_responses_match_for_both_identity_paths(self):
        class HTTPError(Exception):
            pass
        identity = {"uid": self.payload["userId"], "cid": self.payload["courseId"],
                    "rid": "fixture-room", "pub": self.payload["publication"]}
        enrollment_check = Mock()
        key_check = Mock()
        namespace = load_functions(ROOT / "platform/backend/app/api/routes/student_bridge.py",
            {"authorize_student_request"}, {
                "Header": lambda **kwargs: None, "HTTPException": HTTPError,
                "check_student_service_key": key_check, "verify_launch_token": lambda _: identity,
                "_resolve_launch_context": enrollment_check,
                "user_for_cookie": lambda *_: SimpleNamespace(id=uuid.UUID(identity["uid"]), role="student", is_superuser=False),
            })
        _, op = operation(STUDENT_SPEC, "/internal/student/authorize", "post")
        schema = op["responses"]["200"]["content"]["application/json"]["schema"]
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        function = namespace["authorize_student_request"]
        validator.validate(function(SimpleNamespace(launch_token=None, cookie="fixture"), object(), "fixture-key"))
        validator.validate(function(SimpleNamespace(launch_token="fixture", cookie=None), object(), "fixture-key"))
        enrollment_check.assert_called_once()
        self.assertEqual(key_check.call_count, 2)

    def test_real_learning_context_provider_matches_schema_without_database(self):
        class HTTPError(Exception):
            pass
        identity = {"uid": self.payload["userId"], "cid": self.payload["courseId"]}
        classroom = copy.deepcopy(self.payload["classroom"])
        lesson = {"id": "fixture-lesson", "title": "Fixture", "order": 1, "classroom": classroom}
        knowledge_entry = {"id": "fixture-artifact", "resourceType": "knowledge-points",
                           "scope": {"lessonId": "fixture-lesson"},
                           "content": "## 第一周\n### 沙盘\n- 认识组成\n- 做准备"}
        for lessons, entries in (([], []), ([lesson], []), ([lesson], [knowledge_entry])):
            with self.subTest(classroom=bool(lessons), rubric=bool(entries)):
                namespace = load_functions(ROOT / "platform/backend/app/api/routes/student_bridge.py",
                    {"student_learning_context", "_knowledge_artifact_rubric", "_knowledge_points_from_markdown"}, {
                        "Header": lambda **kwargs: None, "HTTPException": HTTPError,
                        "uuid": uuid, "SCHEMA_VERSION": 1, "text": lambda sql: sql,
                        "re": re, "hashlib": hashlib,
                        "check_student_service_key": lambda _: None,
                        "verify_launch_token": lambda _: identity, "_resolve_launch_context": lambda *_: None,
                        "_published_package_payload": lambda *_: {"id": "fixture-publication", "version": 1, "entries": entries},
                        "_published_lessons": lambda *_: lessons, "_classroom_view": lambda *_: copy.deepcopy(classroom),
                        "_grounding_context": lambda *_: {}, "_issue_playback_grant": lambda *_: "fixture-grant",
                    })
                session = SimpleNamespace(execute=lambda *_: SimpleNamespace(first=lambda: ("Fixture course",)))
                result = namespace["student_learning_context"](SimpleNamespace(launch_token="fixture"), session, "fixture-key")
                self.validator.validate(result)
                self.assertEqual(bool(result["lessons"]), bool(lessons))
                self.assertEqual(result["classroom"] is None, not lessons)
                rubric = result["knowledgePackage"].get("rubric")
                if entries:
                    self.assertEqual(rubric["knowledgePoints"][0]["title"], "沙盘")
                    self.assertEqual(rubric["knowledgePoints"][0]["expectedConcepts"], ["认识组成", "做准备"])
                else:
                    self.assertIsNone(rubric)


class TokenCompatibilityTests(unittest.TestCase):
    def namespaces(self, signing_key="fixture-signing", student_key="fixture-signing"):
        settings = SimpleNamespace(STUDENT_TOKEN_SIGNING_KEY=signing_key,
                                   STUDENT_SERVICE_KEY="fixture-channel", STUDENT_LAUNCH_TOKEN_TTL_SECONDS=600)
        common = {"json": json, "base64": base64, "hmac": hmac, "hashlib": hashlib,
                  "time": time, "secrets": secrets, "uuid": uuid, "logging": logging, "__name__": __name__}
        platform = load_functions(ROOT / "platform/backend/app/api/routes/student_bridge.py",
            {"_token_signing_key", "_launch_signature", "issue_launch_token"}, dict(common, settings=settings))
        class LaunchTokenError(ValueError):
            pass
        student = load_functions(ROOT / "student_agent/apps/integration/launch_context.py",
            {"_signature", "verify_launch_token"}, dict(common, LaunchTokenError=LaunchTokenError,
                token_signing_key=lambda: student_key))
        return platform, student, settings

    def test_existing_provider_and_consumer_accept_same_dedicated_key(self):
        platform, student, _ = self.namespaces()
        user_id, course_id = uuid.uuid4(), uuid.uuid4()
        token = platform["issue_launch_token"](user_id, course_id, "fixture-room", {"publicationId": "fixture", "version": 1})
        self.assertEqual(student["verify_launch_token"](token)["uid"], str(user_id))

    def test_legacy_fallback_still_works_and_mismatched_key_is_rejected(self):
        platform, student, _ = self.namespaces("", "fixture-channel")
        with self.assertLogs(__name__, level="WARNING"):
            token = platform["issue_launch_token"](uuid.uuid4(), uuid.uuid4(), "fixture-room", {"version": 1})
        student["verify_launch_token"](token)
        _, wrong_student, _ = self.namespaces(student_key="different-key")
        with self.assertRaises(ValueError):
            wrong_student["verify_launch_token"](token)


if __name__ == "__main__":
    unittest.main()
