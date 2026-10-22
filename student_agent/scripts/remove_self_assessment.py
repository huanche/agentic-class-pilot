"""清理本机运行数据里的结构化自评，不删除聊天、系统评分或其他学情。

运行前应停止学生服务，避免旧进程重新写入字段；正式数据库由 final09 迁移清理。
"""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.integration.data_cleanup import without_self_assessment  # noqa: E402


def clean_runtime(runtime: Path) -> tuple[int, int]:
    changed = 0
    invalid = 0
    for directory in (runtime / "sessions", runtime / "integration"):
        for path in directory.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, UnicodeError):
                invalid += 1
                continue
            cleaned = without_self_assessment(data)
            if cleaned != data:
                path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
                changed += 1
    return changed, invalid


if __name__ == "__main__":
    changed, invalid = clean_runtime(ROOT / "runtime")
    print(f"已清理 {changed} 个运行数据文件；无法解析 {invalid} 个文件。")
    raise SystemExit(1 if invalid else 0)
