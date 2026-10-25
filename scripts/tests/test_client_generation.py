"""Bundling and path safety without running generators or importing apps."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator
from openapi_spec_validator import OpenAPIV31SpecValidator

ROOT = Path(__file__).resolve().parents[2]
module_spec = importlib.util.spec_from_file_location('client_generation', ROOT / 'scripts/generate_integration_clients.py')
generation = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(generation)


class ClientGenerationTests(unittest.TestCase):
    def test_all_bundled_specs_are_valid_and_only_use_internal_refs(self):
        for path in (ROOT / 'contracts').glob('*-api.yaml'):
            with self.subTest(path=path.name):
                spec = generation.bundled_spec(path)
                OpenAPIV31SpecValidator(spec).validate()
                def visit(value):
                    if isinstance(value, dict):
                        if '$ref' in value:
                            self.assertTrue(value['$ref'].startswith('#/components/'))
                        for item in value.values():
                            visit(item)
                    elif isinstance(value, list):
                        for item in value:
                            visit(item)
                visit(spec)

    def test_bundled_context_keeps_fixture_compatibility_and_version_constraint(self):
        spec = generation.bundled_spec(ROOT / 'contracts/internal-student-api.yaml')
        schema = {'$ref': '#/components/schemas/LearningContextV1', 'components': spec['components']}
        validator = Draft202012Validator(schema)
        fixture = json.loads((ROOT / 'contracts/fixtures/platform-learning-context-v1.json').read_text(encoding='utf-8'))
        validator.validate(fixture)
        modified = copy.deepcopy(fixture)
        modified['schemaVersion'] = 2
        self.assertFalse(validator.is_valid(modified))

    def test_generation_destinations_cannot_escape_managed_directory(self):
        self.assertEqual(generation.safe_destination('python/fixture.py'), generation.GENERATED / 'python/fixture.py')
        for value in ('..', '../app.py', '../../.env', str(ROOT / 'platform/.env')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                generation.safe_destination(value)

    def test_snapshot_ignores_bytecode_but_not_stale_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '__pycache__').mkdir()
            (root / '__pycache__/fixture.pyc').write_bytes(b'bytecode')
            (root / 'fixture.py').write_bytes(b'fixture')
            self.assertEqual(generation.snapshot(root), {'fixture.py': b'fixture'})


if __name__ == '__main__':
    unittest.main()
