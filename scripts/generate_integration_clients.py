"""Generate SDK artifacts and mirror the Python clients into service packages.

Run --check to regenerate into an ignored temporary directory and reject drift.
Stale managed files are backed up first; adapters and entry points are untouched.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / 'contracts'
GENERATED = CONTRACTS / 'generated'
PLATFORM_TEACHER_RUNTIME = ROOT / 'platform/backend/app/generated/platform_teacher_api'
PLATFORM_STUDENT_RUNTIME = ROOT / 'platform/backend/app/generated/platform_student_api'
STUDENT_PLATFORM_RUNTIME = ROOT / 'student_agent/generated/student_platform_api'
TOOLING = CONTRACTS / 'tooling'
RUNTIME = ROOT / '.runtime'
GENERATOR_PYTHON = '3.14.4'
PYTHON_CLIENTS = {
    'student_platform_api': 'internal-student-api.yaml',
    'platform_teacher_api': 'teacher-service-api.yaml',
    'platform_student_api': 'student-service-api.yaml',
}


def normalized_digest(path: Path) -> str:
    return hashlib.sha256(path.read_text(encoding='utf-8').encode()).hexdigest()


def bundled_spec(path: Path) -> dict:
    spec = yaml.safe_load(path.read_text(encoding='utf-8'))
    schemas = spec.setdefault('components', {}).setdefault('schemas', {})
    reference_names = {'./learning-context.schema.json': 'LearningContextV1'}

    def rewrite(value, definitions=None):
        if isinstance(value, list):
            return [rewrite(item, definitions) for item in value]
        if not isinstance(value, dict):
            return value
        reference = value.get('$ref')
        if reference in reference_names:
            name = reference_names[reference]
            if name not in schemas:
                external = (path.parent / reference).resolve()
                if not external.is_relative_to(CONTRACTS.resolve()):
                    raise ValueError('Refusing schema reference outside contracts')
                schema = json.loads(external.read_text(encoding='utf-8'))
                local_definitions = {key: name + key[:1].upper() + key[1:] for key in schema.get('$defs', {})}
                for key, definition in schema.get('$defs', {}).items():
                    schemas[local_definitions[key]] = rewrite(definition, local_definitions)
                schemas[name] = rewrite({key: item for key, item in schema.items() if key not in {'$schema', '$id', '$defs'}}, local_definitions)
            return {'$ref': '#/components/schemas/' + name}
        if reference and reference.startswith('#/$defs/'):
            return {'$ref': '#/components/schemas/' + definitions[reference.removeprefix('#/$defs/')]}
        if reference and not reference.startswith('#/components/'):
            raise ValueError(f'Unsupported schema reference: {reference}')
        result = {key: rewrite(item, definitions) for key, item in value.items()}
        if 'const' in result:
            result['enum'] = [result.pop('const')]
        return result

    # References may register components while traversing response schemas.
    result = rewrite(copy.deepcopy(spec))
    result.setdefault('components', {}).setdefault('schemas', {}).update(schemas)
    return result


def run(command: list[str], cwd: Path) -> None:
    # The Python generator iterates a set of union types. Stabilize its order.
    completed = subprocess.run(command, cwd=cwd, env={**os.environ, 'PYTHONHASHSEED': '0'})
    if completed.returncode:
        raise RuntimeError('Client generator failed; no application files were changed')


def snapshot(directory: Path) -> dict[str, bytes]:
    if not directory.exists():
        return {}
    return {path.relative_to(directory).as_posix(): path.read_bytes()
            for path in directory.rglob('*') if path.is_file()
            and '__pycache__' not in path.parts and path.suffix != '.pyc'}


def safe_destination(relative: str) -> Path:
    target = (GENERATED / relative).resolve()
    if not target.is_relative_to(GENERATED.resolve()) or target == GENERATED.resolve():
        raise ValueError('Refusing generated output outside contracts/generated')
    return target


def generate(output: Path) -> None:
    requirement = (TOOLING / 'requirements-generators.txt').read_text().splitlines()
    python_version = next(line.split('==')[1] for line in requirement if line.startswith('openapi-python-client=='))
    package = json.loads((TOOLING / 'package.json').read_text())
    specs = output / 'specs'
    specs.mkdir(parents=True)
    for filename in {'internal-teacher-api.yaml', *PYTHON_CLIENTS.values()}:
        document = bundled_spec(CONTRACTS / filename)
        (specs / (Path(filename).stem + '.json')).write_text(
            json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8', newline='\n')
    for name, source in PYTHON_CLIENTS.items():
        config = output.parent / f'{name}-config.json'
        config.write_text(json.dumps({'package_name_override': name, 'post_hooks': []}), encoding='utf-8')
        target = output / 'python' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        run(['uv', 'tool', 'run', '--python', GENERATOR_PYTHON,
             '--with-requirements', str(TOOLING / 'requirements-generators.lock'),
             '--from', f'openapi-python-client=={python_version}', '--no-env-file',
             'openapi-python-client', 'generate', '--path', str(specs / (Path(source).stem + '.json')),
             '--config', str(config), '--meta', 'none', '--fail-on-warning', '--output-path', str(target)], output.parent)
    run(['node', str(TOOLING / 'generate-typescript.mjs'),
         str(specs / 'internal-teacher-api.json'), str(output / 'typescript/teacher_platform_api')], TOOLING)
    # Generator outputs must compare identically on Windows and Linux.
    for path in output.rglob('*'):
        if path.is_file():
            content = '\n'.join(line.rstrip() for line in path.read_text(encoding='utf-8').splitlines()).rstrip() + '\n'
            path.write_text(content, encoding='utf-8', newline='\n')
    files = sorted(snapshot(output))
    manifest = {
        'formatVersion': 1,
        'generators': {'openapi-python-client': python_version, '@hey-api/openapi-ts': package['devDependencies']['@hey-api/openapi-ts']},
        'generatorPython': GENERATOR_PYTHON,
        'pythonToolLock': normalized_digest(TOOLING / 'requirements-generators.lock'),
        'sources': {path.name: normalized_digest(path) for path in sorted(CONTRACTS.glob('*-api.yaml'))},
        'learningContextSchema': normalized_digest(CONTRACTS / 'learning-context.schema.json'),
        'nodeToolLock': normalized_digest(TOOLING / 'package-lock.json'),
        'files': files,
    }
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if not (TOOLING / 'node_modules/@hey-api/openapi-ts/package.json').is_file():
        raise RuntimeError('Install pinned tools first: npm ci --ignore-scripts --prefix contracts/tooling')
    RUNTIME.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='integration-clients-', dir=RUNTIME) as directory:
        output = Path(directory) / 'generated'
        generate(output)
        expected, current = snapshot(output), snapshot(GENERATED)
        drift = sorted(path for path in set(expected) | set(current) if expected.get(path) != current.get(path))
        runtime_clients = {
            'platform': (output / 'python/platform_teacher_api', PLATFORM_TEACHER_RUNTIME),
            'platform-student': (output / 'python/platform_student_api', PLATFORM_STUDENT_RUNTIME),
            'student': (output / 'python/student_platform_api', STUDENT_PLATFORM_RUNTIME),
        }
        runtime_snapshots = {
            name: (snapshot(source), snapshot(target))
            for name, (source, target) in runtime_clients.items()
        }
        runtime_drift = [
            f'{name} runtime: {path}'
            for name, (source, target) in runtime_snapshots.items()
            for path in sorted(set(source) | set(target))
            if source.get(path) != target.get(path)
        ]
        if args.check:
            if drift or runtime_drift:
                print('Generated clients drifted:\n' + '\n'.join(drift + runtime_drift))
                return 1
            print('Generated clients are reproducible and current.')
            return 0
        # Preserve stale generated artifacts in an ignored backup, never delete user code.
        for relative in set(current) - set(expected):
            source = safe_destination(relative)
            backup = RUNTIME / 'generated-client-backups' / str(time.time_ns()) / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(source, backup)
        for relative, content in expected.items():
            target = safe_destination(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        # Deployable services do not include contracts/ on their import path.
        # Runtime packages must match the canonical generated SDK bytes.
        for name, (runtime_expected, runtime_current) in runtime_snapshots.items():
            destination = runtime_clients[name][1]
            for relative in set(runtime_current) - set(runtime_expected):
                source = destination / relative
                backup = RUNTIME / 'generated-client-backups' / str(time.time_ns()) / f'{name}-runtime' / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(source, backup)
            for relative, content in runtime_expected.items():
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        print(f'Generated {len(expected)} files under contracts/generated and mirrored runtime clients.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
