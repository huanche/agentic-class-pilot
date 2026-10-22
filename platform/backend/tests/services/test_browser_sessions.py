"""Origin 校验的回环地址等价（本地 127.0.0.1 vs localhost 的 403 坑）。"""

from app.core.config import settings
from app.services.browser_sessions import _loopback_equivalent


def test_loopback_variants_are_equivalent() -> None:
    frontend = "http://localhost:8088"
    assert _loopback_equivalent("http://127.0.0.1:8088", frontend)
    assert _loopback_equivalent("http://[::1]:8088", frontend)
    assert _loopback_equivalent(frontend, frontend)


def test_other_origins_still_rejected() -> None:
    frontend = "http://localhost:8088"
    assert not _loopback_equivalent("https://evil.example", frontend)
    assert not _loopback_equivalent("http://evil.example:8088", frontend)
    assert not _loopback_equivalent("http://localhost:3000", frontend)  # 端口不同
    assert not _loopback_equivalent("", frontend)
    # 生产域名（非回环）永不等价
    assert not _loopback_equivalent("http://localhost:8088", "https://edu.example.com")


def test_real_frontend_host_unchanged_semantics() -> None:
    # 现网配置是正式域名时，回环来源照样被拒——生产行为不变
    assert not _loopback_equivalent("http://127.0.0.1:8088", "https://edu.example.com")
