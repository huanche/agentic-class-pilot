"""Enable/restore only local TTS env fields; never read or print API keys."""

import argparse
import json
from pathlib import Path
import re


VALUES = {
    "TTS_LEMONADE_BASE_URL": "http://127.0.0.1:13305/v1",
    "TTS_LEMONADE_MODELS": "kokoro-v1",
    "TTS_LEMONADE_VOICE": "zf_xiaoyi",
    "TTS_QWEN_ENABLED": "false",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()
    teacher = Path(__file__).resolve().parents[2]
    envfile = teacher / ".env.local"
    backup = teacher / ".runtime" / "kokoro" / "previous-local-tts.json"
    text = envfile.read_text(encoding="utf-8-sig") if envfile.exists() else ""
    pattern = r"(?m)^({})=[^\r\n]*(?:\r?\n|$)".format("|".join(VALUES))
    if args.restore:
        saved = json.loads(backup.read_text(encoding="utf-8"))
        lines = saved["lines"]
    else:
        if not backup.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            lines = [match.group(0).rstrip("\r\n") for match in re.finditer(pattern, text)]
            backup.write_text(json.dumps({"lines": lines}, indent=2), encoding="utf-8")
        lines = [f"{key}={value}" for key, value in VALUES.items()]
    text = re.sub(pattern, "", text).rstrip("\r\n")
    envfile.write_text(text + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
    print("Local TTS configuration restored." if args.restore else "Local Kokoro enabled; cloud Qwen TTS disabled only in this checkout.")


if __name__ == "__main__":
    main()
