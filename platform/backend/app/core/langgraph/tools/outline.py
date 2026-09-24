"""Tools for the outline agent (teacher-side teaching-outline generation).

Private to this agent — deliberately NOT appended to the shared chat
registry in ``tools/__init__.py`` — so each agent keeps its own tool set
and the tool bindings never cross agents (inventory gap #5). A pure
function was chosen on purpose: no DB access means no authorisation
surface to design yet. Tools that read course/chapter data land here
later, once InjectedToolArg-style permission injection exists (see
docs/langgraph-migration-plan.md §2.1).
"""

from langchain_core.tools import BaseTool, tool


@tool
async def suggest_weekly_plan(total_hours: int, weeks: int) -> str:
    """按教学周数平均分配总课时，并给出前松后紧的节奏建议。

    Args:
        total_hours: 课程总课时数（例如 48）。
        weeks: 教学周数（例如 16）。
    """
    if total_hours <= 0:
        return "错误：total_hours 必须为正整数。"
    if weeks <= 0:
        return "错误：weeks 必须为正整数。"
    per_week, remainder = divmod(total_hours, weeks)
    lines = [f"总课时 {total_hours}，教学周数 {weeks}："]
    if remainder == 0:
        lines.append(f"- 每周 {per_week} 课时，均匀分布。")
    else:
        lines.append(
            f"- 每周基础 {per_week} 课时，其中 {remainder} 周每周多 1 课时"
            "（建议安排在前半学期，课程导入期内容较重）。"
        )
    if weeks >= 8:
        lines.append(
            "- 节奏建议：前 1/3 学期以讲授为主，中段加入课堂练习，"
            "最后两周留复习与考核。"
        )
    return "\n".join(lines)


outline_tools: list[BaseTool] = [suggest_weekly_plan]
