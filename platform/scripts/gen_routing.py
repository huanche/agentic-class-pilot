"""Generate gateway route snippets from contracts/routing.yaml (single source).

Usage:
    python platform/scripts/gen_routing.py          # regenerate derived files
    python platform/scripts/gen_routing.py --check  # verify derived files are current

Derived files (do not edit by hand):
    platform/deployment/generated/gateway-routes-<env>.conf

Each Caddyfile imports its snippet, so the route rules are maintained only in
contracts/routing.yaml. The generator reproduces the existing Caddyfiles byte
for byte (comments and route order included); no behavior changes here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ROUTING_YAML = ROOT / "contracts" / "routing.yaml"
GENERATED_DIR = ROOT / "platform" / "deployment" / "generated"

HEADER = "# GENERATED from contracts/routing.yaml — do not edit by hand.\n" \
         "# Run: python platform/scripts/gen_routing.py\n\n"


def render_route(route: dict, services: dict, upstream_key: str) -> str:
    """Render one route entry exactly in the existing Caddyfile style."""
    lines: list[str] = []
    for note in route.get("comment") or []:
        lines.append(f"  # {note}")
    kind = route["type"]
    upstream = None
    if "service" in route:
        upstream = services[route["service"]][upstream_key]
    if kind == "redirect":
        lines.append(f"  handle {route['path']} {{")
        lines.append(f"    redir * {route['to']} {route['code']}")
        lines.append("  }")
    elif kind == "handle_path":
        lines.append(f"  handle_path {route['path']} {{")
        lines.append(f"    reverse_proxy {upstream}")
        lines.append("  }")
    elif kind == "proxy":
        lines.append(f"  handle {route['path']} {{")
        lines.append(f"    reverse_proxy {upstream}")
        lines.append("  }")
    elif kind == "fallback":
        lines.append("  handle {")
        lines.append(f"    reverse_proxy {upstream}")
        lines.append("  }")
    else:
        raise SystemExit(f"Unknown route type: {kind!r}")
    return "\n".join(lines)


def render_snippet(services: dict, spec: dict) -> str:
    upstream_key = spec["upstream"]
    blocks = [
        ("\n" if route.get("blank_before") else "")
        + render_route(route, services, upstream_key)
        for route in spec["routes"]
    ]
    return HEADER + "\n".join(blocks) + "\n"


def main() -> None:
    check_only = "--check" in sys.argv[1:]
    spec_all = yaml.safe_load(ROUTING_YAML.read_text(encoding="utf-8"))
    services = spec_all["services"]
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    mismatched: list[str] = []
    for env_name, env_spec in spec_all["environments"].items():
        target = GENERATED_DIR / f"gateway-routes-{env_name}.conf"
        content = render_snippet(services, env_spec)
        if check_only:
            if not target.exists() or target.read_text(encoding="utf-8") != content:
                mismatched.append(str(target))
        else:
            target.write_text(content, encoding="utf-8", newline="\n")
            print(f"written: {target.relative_to(ROOT)}")

    if check_only:
        if mismatched:
            print("Derived files are out of date. Run: python platform/scripts/gen_routing.py")
            for path in mismatched:
                print(f"  outdated: {path}")
            raise SystemExit(1)
        print("All derived routing files are up to date.")


if __name__ == "__main__":
    main()
