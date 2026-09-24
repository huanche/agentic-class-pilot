"""One-shot launcher for the classroom session server.

Usage:
    python apps/start.py                 # start on 0.0.0.0:8000 and open browser
    python apps/start.py --scale 12      # open with 12x time compression (45min -> ~4min)
    python apps/start.py --port 8080     # another port
    python apps/start.py --no-browser    # server only (e.g. already-on machine)
"""

from __future__ import annotations

import argparse
import importlib.util
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_PORT = 8000


def missing_deps() -> list[str]:
    return [m for m in ("fastapi", "uvicorn") if importlib.util.find_spec(m) is None]


def lan_ip() -> str:
    """Best-effort LAN address so students can join from their phones."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(1)
    try:
        s.connect(("223.5.5.5", 80))
        return str(s.getsockname()[0])
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def wait_and_open(url: str, timeout: float = 30.0) -> None:
    """Open the browser only after the server actually answers."""
    # 本地服务不走系统代理：挂着 HTTP_PROXY 的机器上 urllib 会被代理拦下
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with opener.open(url, timeout=2):
                break
        except Exception:
            time.sleep(0.4)
    else:
        print(f"[!] service did not come up in time; open manually: {url}", flush=True)
        return
    time.sleep(0.3)
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main() -> int:
    p = argparse.ArgumentParser(description="Start the classroom session server")
    p.add_argument("--host", default="0.0.0.0", help="bind address (default 0.0.0.0)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument(
        "--scale",
        type=int,
        default=0,
        help="time compression for rehearsal, e.g. 12 = 45min to about 4min",
    )
    p.add_argument("--no-browser", action="store_true", help="do not auto-open a browser")
    a = p.parse_args()

    miss = missing_deps()
    if miss:
        print(f"[x] missing packages: {' '.join(miss)}", flush=True)
        print(
            f"    run first:  {sys.executable} -m pip install {' '.join(miss)}",
            flush=True,
        )
        return 1

    query = f"?scale={a.scale}" if a.scale and a.scale > 1 else ""
    local = f"http://127.0.0.1:{a.port}/app{query}"

    banner = [
        "=" * 56,
        "  classroom is ready",
        f"  student UI    : {local}",
        f"  teacher page  : http://127.0.0.1:{a.port}/",
        (
            f"  phones (LAN)  : http://{lan_ip()}:{a.port}/app{query}"
            if a.host in ("0.0.0.0", "::", "[::]")
            else None
        ),
        "  stop it       : Ctrl+C in this window",
        "  do NOT sleep  : the clock is real time, sleep skips the lesson",
        "=" * 56,
    ]
    # flush matters: stdout is block-buffered when redirected, so a double-click
    # user would see nothing until Ctrl+C.
    print("\n".join(line for line in banner if line), flush=True)

    if not a.no_browser:
        threading.Thread(target=wait_and_open, args=(local,), daemon=True).start()

    import uvicorn

    uvicorn.run("apps.server:app", host=a.host, port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
