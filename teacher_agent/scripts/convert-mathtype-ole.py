"""Convert one MathType/Equation Editor OLE object to presentation MathML.

The bundled parser is MIT-licensed mathtypejx; olefile is BSD-licensed.  This
small stdin/stdout adapter keeps untrusted Office data out of command-line
arguments and gives the Next.js route a stable process boundary.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    vendor = Path(__file__).resolve().parents[1] / "vendor" / "formula-converter"
    sys.path.insert(0, str(vendor))
    try:
        from mtef.mathml import mtef_to_mathml
    except Exception as exc:
        print(json.dumps({"error": f"formula parser unavailable: {exc}"}), file=sys.stderr)
        return 2

    payload = sys.stdin.buffer.read(10 * 1024 * 1024 + 1)
    if not payload or len(payload) > 10 * 1024 * 1024:
        print(json.dumps({"error": "invalid OLE payload"}), file=sys.stderr)
        return 3

    mathml = mtef_to_mathml(payload)
    if not mathml:
        print(json.dumps({"error": "unsupported or malformed MathType equation"}), file=sys.stderr)
        return 4

    sys.stdout.buffer.write(json.dumps({"mathml": mathml}, ensure_ascii=False).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
