"""Small stdio bridge for the official DeepSeek Harness Python SDK."""
from __future__ import annotations

import os
import sys

from deepseek_harness import DeepSeekHarness


def main() -> None:
    prompt = sys.stdin.read()
    workspace = os.environ["DSH_WORKSPACE"]
    dsh_home = os.environ.get("DSH_HOME", os.path.join(workspace, ".dsh"))
    with DeepSeekHarness(
        dsh_home=dsh_home,
        cwd=workspace,
        profile=os.environ.get("DSH_PROFILE", "sdk-minimal"),
        provider=os.environ.get("DSH_PROVIDER", "deepseek-official"),
        model=os.environ.get("DSH_MODEL", "deepseek-v4-flash"),
    ) as harness:
        result = harness.run(prompt, session_id=os.environ["DSH_SESSION_ID"])
    print(result.final_response)


if __name__ == "__main__":
    main()
