"""将本机旧会话切换到唯一掌握记录；不合并两套分数，不追溯重评。"""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apps.integration.mastery import normalize_mastery_state  # noqa: E402


def migrate_sessions(directory: Path) -> int:
    changed = 0
    for path in directory.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        normalized = normalize_mastery_state(dict(data))
        if normalized != data:
            path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
            changed += 1
    return changed


if __name__ == "__main__":
    print(f"已将 {migrate_sessions(ROOT / 'runtime' / 'sessions')} 个旧会话切换为唯一掌握记录。")
