"""移除已下线的结构化自评字段，保留其余学习记录。"""

RETIRED_SELF_ASSESSMENT_KEYS = frozenset({
    "self_rating", "self_ratings", "tutoring_self_ratings", "_persisted_self_ratings",
})


def without_self_assessment(value):
    """兼容旧会话与旧报告；不让已删除的字段再次保存或通过接口返回。"""
    if isinstance(value, dict):
        return {key: without_self_assessment(item) for key, item in value.items()
                if key not in RETIRED_SELF_ASSESSMENT_KEYS}
    if isinstance(value, list):
        return [without_self_assessment(item) for item in value]
    return value
