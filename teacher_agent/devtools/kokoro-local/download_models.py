"""Download the official Kokoro ONNX release into the project runtime folder."""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import urllib.request

ASSETS = {
    "kokoro-v1.0.onnx": 325532387,
    "voices-v1.0.bin": 28214398,
}
RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"


def download(directory: Path, name: str, expected_size: int):
    target = directory / name
    if not target.exists() or target.stat().st_size != expected_size:
        temporary = target.with_suffix(target.suffix + ".partial")
        for attempt in range(3):
            offset = temporary.stat().st_size if temporary.exists() else 0
            request = urllib.request.Request(RELEASE + name, headers={
                "User-Agent": "AgenticClassPilot-local-kokoro",
                **({"Range": f"bytes={offset}-"} if offset else {}),
            })
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    append = offset > 0 and response.status == 206
                    if not append:
                        offset = 0
                    checkpoint = offset
                    with temporary.open("ab" if append else "wb") as output:
                        while chunk := response.read(1024 * 1024):
                            output.write(chunk)
                            offset += len(chunk)
                            if offset - checkpoint >= 32 * 1024 * 1024:
                                print(json.dumps({"file": name, "downloadedMB": round(offset / 1e6, 1)}), flush=True)
                                checkpoint = offset
                if temporary.stat().st_size != expected_size:
                    raise RuntimeError(f"Unexpected file size for {name}")
                temporary.replace(target)
                break
            except Exception as error:
                print(json.dumps({"file": name, "attempt": attempt + 1, "error": str(error)[:160]}), flush=True)
                if attempt == 2:
                    raise
    digest = hashlib.sha256()
    with target.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return {"file": name, "bytes": target.stat().st_size, "sha256": digest.hexdigest(), "source": RELEASE + name}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    directory = args.root.resolve() / "models"
    directory.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        reports = list(pool.map(lambda pair: download(directory, *pair), ASSETS.items()))
    (directory / "manifest.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
    print(json.dumps({"modelsReady": True, "files": reports}), flush=True)
