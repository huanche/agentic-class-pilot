"""Export recent service diagnostics for the platform console on the host."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "platform" / "backend"))

from app.services.diagnostic_logs import parse_event  # noqa: E402

SOURCES = {
    "platform": ["journalctl", "-u", "agentic-platform", "-o", "cat", "-n", "2000", "--no-pager"],
    "student": ["journalctl", "-u", "agentic-student", "-o", "cat", "-n", "2000", "--no-pager"],
    "teacher": ["docker", "logs", "--tail", "2000", "agentic-teacher-prod"],
}


def collect(directory: Path, service: str) -> None:
    result = subprocess.run(SOURCES[service], capture_output=True, timeout=15, check=True)
    streams = [result.stdout]
    if service == "teacher":
        streams.append(result.stderr)
    events = []
    for stream in streams:
        for line in stream.decode("utf-8", errors="replace").splitlines():
            parsed = parse_event(line, service)
            if parsed is not None:
                events.append(parsed)
    events.sort(key=lambda item: item[0])

    target = directory / f"{service}-current.stdout.log"
    output = NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False)
    temporary = Path(output.name)
    try:
        with output:
            for _, event in events:
                output.write(json.dumps(event, ensure_ascii=False) + "\n")
        os.chmod(temporary, 0o640)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--service", choices=SOURCES, action="append")
    args = parser.parse_args()
    failed = False
    for service in args.service or SOURCES:
        try:
            collect(args.directory, service)
        except (OSError, subprocess.SubprocessError) as error:
            print(f"{service}: {error}", file=sys.stderr)
            failed = True
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
