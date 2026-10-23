"""Fetch the official pinned Python runtime and ONNX weights into ignored local storage."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

from huggingface_hub import HfApi, snapshot_download

UPSTREAM_REVISION = 'fc8d11832644890a6c490033fc9e00c57e35a73d'
UPSTREAM = f'https://raw.githubusercontent.com/HojoAI/Hojo-TTS-Light/{UPSTREAM_REVISION}/'
REPOS = {'40m': 'HojoAI/Hojo-TTS-Light-40M', '80m': 'HojoAI/Hojo-TTS-Light'}


def prepare(root: Path, sizes: list[str]):
    root.mkdir(parents=True, exist_ok=True)
    manifest = {'runtimeRevision': UPSTREAM_REVISION, 'models': {}}
    for size in sizes:
        source = root / 'upstream' / size
        source.mkdir(parents=True, exist_ok=True)
        files = ['onnx_model.py', 'text_normalize.py']
        if size == '80m':
            files.append('assets/zh1.wav')
        for name in files:
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_bytes(urlopen(f'{UPSTREAM}Hojo-TTS-Light-{size.upper()}/{name}', timeout=60).read())
        (root / 'UPSTREAM-LICENSE.txt').write_bytes(urlopen(UPSTREAM + 'LICENSE.txt', timeout=60).read())
        model = root / 'models' / size
        # Persist the resolved revision so a restart never silently downloads a new model.
        stamp = root / f'{size}-revision.txt'
        revision = stamp.read_text().strip() if stamp.exists() else HfApi().model_info(REPOS[size]).sha
        snapshot_download(REPOS[size], revision=revision, local_dir=model,
                          allow_patterns=['*.onnx', '*.npz', '*.json'], max_workers=2)
        stamp.write_text(revision, encoding='ascii')
        records = []
        for path in sorted(model.glob('*')):
            if path.is_file():
                with path.open('rb') as file:
                    checksum = hashlib.file_digest(file, 'sha256').hexdigest()
                records.append({'name': path.name, 'bytes': path.stat().st_size,
                                'sha256': checksum})
        manifest['models'][size] = {'repo': REPOS[size], 'revision': revision, 'files': records}
        print(json.dumps({'modelReady': size, 'files': len(records)}), flush=True)
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--models', nargs='+', choices=list(REPOS), default=['40m', '80m'])
    args = parser.parse_args()
    prepare(args.root.resolve(), args.models)
