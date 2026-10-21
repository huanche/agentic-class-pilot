"""Run with platform/.venv/Scripts/python.exe -m unittest discover -s scripts/tests."""
import fnmatch
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("local_dev", ROOT / "scripts/local_dev.py")
local = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local)


def fixture_config():
    return {
        "ENVIRONMENT": "development",
        "DATABASE_URL": "postgresql://platform:example-secret@127.0.0.1:55432/education",
        "POSTGRES_PASSWORD": "example-secret", "TEACHER_DB_PASSWORD": "teacher-secret",
        "STUDENT_DATABASE_URL": "postgresql://student:student-secret@127.0.0.1:55432/education",
        "TEACHER_SERVICE_KEY": "teacher-channel", "STUDENT_SERVICE_KEY": "student-channel",
        "STUDENT_TOKEN_SIGNING_KEY": "signing-secret", "SECRET_KEY": "application-secret",
    }


class LocalConfigurationTests(unittest.TestCase):
    def configure(self, config):
        with patch.object(local, "read_env", return_value=config):
            return local.configuration()

    def test_rejects_nonlocal_database_targets(self):
        for url in ("postgresql://platform:secret@remote.example:55432/education",
                    "postgresql://platform:secret@127.0.0.1:5432/education",
                    "postgresql://platform:secret@127.0.0.1:55432/another_project"):
            with self.subTest(url=url), self.assertRaises(local.LocalError):
                local.check_database_target(url, "platform")

    def test_rejects_production_configuration(self):
        config = fixture_config()
        config["ENVIRONMENT"] = "production"
        with self.assertRaisesRegex(local.LocalError, "development"):
            self.configure(config)

    def test_rejects_inconsistent_password_without_disclosing_it(self):
        config = fixture_config()
        config["POSTGRES_PASSWORD"] = "different-secret"
        with self.assertRaises(local.LocalError) as caught:
            self.configure(config)
        self.assertNotIn("different-secret", str(caught.exception))
        self.assertNotIn("example-secret", str(caught.exception))

    def test_accepts_percent_encoded_database_password(self):
        config = fixture_config()
        config["POSTGRES_PASSWORD"] = "example@pass:word"
        config["DATABASE_URL"] = "postgresql://platform:example%40pass%3Aword@127.0.0.1:55432/education"
        self.assertEqual(self.configure(config), config)

    def test_rejects_empty_and_placeholder_signing_keys(self):
        for value in ("", "change-me-64-hex-chars"):
            config = fixture_config()
            config["STUDENT_TOKEN_SIGNING_KEY"] = value
            with self.subTest(value=value), self.assertRaisesRegex(local.LocalError, "STUDENT_TOKEN_SIGNING_KEY"):
                self.configure(config)

    def test_student_personal_model_settings_cannot_override_shared_identity(self):
        config = fixture_config()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env.local").write_text("STUDENT_SERVICE_KEY=wrong\nAGENT_LLM_MODEL=personal-model\n")
            with patch.object(local, "STUDENT", root):
                env = local.environment(config, "student")
        self.assertEqual(env["STUDENT_SERVICE_KEY"], "student-channel")
        self.assertEqual(env["STUDENT_TOKEN_SIGNING_KEY"], "signing-secret")
        self.assertEqual(env["AGENT_LLM_MODEL"], "personal-model")
        self.assertEqual(env["PLATFORM_AUTH_URL"], "http://127.0.0.1:8080/api/v1")

    def test_teacher_uses_one_public_origin_and_independent_storage_secret(self):
        config = fixture_config()
        config["MINIO_ROOT_PASSWORD"] = "object-secret"
        with patch.dict(os.environ, {"DATABASE_URL": "inherited-wrong", "ACCESS_CODE": "wrong"}):
            env = local.environment(config, "teacher")
        for key in ("PLATFORM_PUBLIC_URL", "FRONTEND_HOST", "NEXT_PUBLIC_SAAS_HOST_ORIGIN", "ALLOWED_FRAME_ANCESTORS"):
            self.assertEqual(env[key], "http://localhost:8088")
        self.assertNotIn("DATABASE_URL", env)
        self.assertNotIn("ACCESS_CODE", env)
        self.assertEqual(env["COURSE_OBJECT_STORAGE_SECRET_KEY"], "object-secret")

    def test_open_but_broken_minio_forwarding_is_not_treated_as_ready(self):
        config = {"COURSE_OBJECT_STORAGE_MODE": "minio",
                  "COURSE_OBJECT_STORAGE_ENDPOINT": "http://127.0.0.1:59000"}
        with patch.object(local.HTTP, "open", side_effect=OSError("connection closed")):
            with self.assertRaisesRegex(local.LocalError, "MinIO HTTP health failed"):
                local.check_infrastructure(config)

    def test_rejects_nonlocal_object_storage_before_probing(self):
        config = {"COURSE_OBJECT_STORAGE_MODE": "minio",
                  "COURSE_OBJECT_STORAGE_ENDPOINT": "https://production.example"}
        with patch.object(local.HTTP, "open") as probe:
            with self.assertRaises(local.LocalError):
                local.check_infrastructure(config)
            probe.assert_not_called()

    def test_platform_asset_changes_invalidate_build_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "public").mkdir()
            asset = root / "public/logo.svg"
            asset.write_text("before")
            before = local.fingerprint(root, (), ("src", "public"))
            asset.write_text("after")
            self.assertNotEqual(before, local.fingerprint(root, (), ("src", "public")))

    def test_this_fix_does_not_match_existing_main_deploy_filters(self):
        import yaml
        changed = ("start-local.ps1", "scripts/local_dev.py", "scripts/local-gateway.mjs",
                   "scripts/tests/test_local_dev.py", "scripts/tests/local-gateway.test.mjs",
                   "README.md", "docs/local-full-stack.md")
        checked = 0
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
            push = (workflow.get("on", workflow.get(True)) or {}).get("push")
            if not isinstance(push, dict) or "main" not in push.get("branches", []):
                continue
            checked += 1
            self.assertTrue(push.get("paths"), f"{path.name} has an unfiltered main push trigger")
            for filename in changed:
                self.assertFalse(any(fnmatch.fnmatchcase(filename, pattern) for pattern in push["paths"]),
                                 f"{filename} triggers {path.name}")
        self.assertGreaterEqual(checked, 3)


if __name__ == "__main__":
    unittest.main()
