"""Contract consistency check: declared internal-API paths must exist in code.

Run:  python platform/scripts/check_contracts.py   (CI-safe, no network)

Guards against the agreement documents drifting from the implementation:
every path declared in contracts/internal-*.yaml must appear as a route in
the corresponding platform router file, and every declared auth header must
be read somewhere in the backend code.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"
BACKEND = ROOT / "platform" / "backend" / "app"

SOURCES = {
    "contracts/internal-teacher-api.yaml": [
        BACKEND / "api" / "routes" / "teacher_bridge.py",
        BACKEND / "api" / "routes" / "user_model_config.py",
    ],
    "contracts/internal-student-api.yaml": [
        BACKEND / "api" / "routes" / "student_bridge.py",
        BACKEND / "api" / "routes" / "user_model_config.py",
    ],
}


def main() -> None:
    problems: list[str] = []
    for spec_rel, source_files in SOURCES.items():
        spec_path = ROOT / spec_rel
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
        code = "\n".join(f.read_text(encoding="utf-8") for f in source_files)
        for path in spec.get("paths", {}):
            # spec paths carry the /api/v1 prefix; router decorators do not
            inner = path.replace("/api/v1", "", 1)
            decorators = (f'"{inner}"', f"'{inner}'")
            if not any(decorator in code for decorator in decorators):
                problems.append(f"{spec_rel}: 路径 {path} 未在平台代码中找到对应路由")
        for scheme in (spec.get("components", {}).get("securitySchemes") or {}).values():
            header = scheme.get("name", "")
            # FastAPI 以下划线参数名声明请求头（X-Teacher-Service-Key → x_teacher_service_key）
            snake = header.lower().replace("-", "_")
            if header and header not in code and snake not in code:
                problems.append(f"{spec_rel}: 认证头 {header} 未在平台代码中使用")
    if problems:
        print("接口约定与代码不一致：")
        for problem in problems:
            print(f"  - {problem}")
        raise SystemExit(1)
    print("接口约定校验通过：声明的路径与认证头均存在于平台实现中。")


if __name__ == "__main__":
    main()
