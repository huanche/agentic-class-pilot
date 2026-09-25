"""数据接入 + 整理 + 规划课时 + 落盘入口。

用法（项目根目录下）：
    python ingest/run.py --course operating-systems --lesson ch3-process-scheduling
    python ingest/run.py --course X --lesson Y --scaffold     # 只建骨架 + 默认 lesson-plan

流程：DataSource.fetch_* → extract → plan（时长/阶段）→ store。
数据源用 FileDataSource（ingest/sample 样例脏数据）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 允许 `python ingest/run.py` 直接运行：把项目根加进 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.datasource import DataSource, FileDataSource
from ingest import extract, plan, store


def _resolve_source(kind: str) -> DataSource:
    """选数据源。数据库数据源已撤，统一用 file 样例源。"""
    return FileDataSource()


def ingest(course_id: str, lesson_id: str, source: DataSource | None = None,
           video_minutes: int = 0) -> dict:
    """读取 → 整理 → 规划课时 → 存放。返回本轮处理摘要。"""
    source = source or _resolve_source("file")
    syllabus = source.fetch_syllabus(course_id, lesson_id)
    transcript = source.fetch_transcript(course_id, lesson_id)

    if syllabus is None:
        raise SystemExit(f"未找到大纲数据：{course_id}/{lesson_id}（检查数据源）")

    points = extract.extract_knowledge_points(syllabus)
    goals = extract.extract_goals(syllabus)
    clean_sub = extract.clean_transcript(transcript or "")

    store.update_knowledge_base(points)
    rel = store.write_lesson_data(course_id, lesson_id, points, goals, clean_sub)

    # 课时计划：总时长（读不到默认 40）→ 视频 → 剩余 → AI/规则分阶段
    total = extract.extract_duration(syllabus) or plan.DEFAULT_TOTAL_MINUTES
    plan_doc = plan.build_plan(
        course_id=course_id, lesson_id=lesson_id,
        total_minutes=total, video_minutes=video_minutes, syllabus=syllabus,
    )
    plan_rel = store.write_lesson_plan(course_id, lesson_id, plan_doc)

    return {
        "course_id": course_id,
        "lesson_id": lesson_id,
        "knowledge_points": len(points),
        "goals": len(goals),
        "transcript_chars": len(clean_sub),
        "total_minutes": total,
        "written_to": rel,
        "lesson_plan": plan_rel,
    }


def scaffold(course_id: str, lesson_id: str) -> str:
    """只建目录骨架 + 一份默认 lesson-plan（不读数据源，创建课程时用）。"""
    rel = store.write_lesson_data(course_id, lesson_id, [], [], "")
    plan_doc = plan.build_plan(course_id=course_id, lesson_id=lesson_id)
    store.write_lesson_plan(course_id, lesson_id, plan_doc)
    return rel


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从数据源读取大纲+字幕，整理后落盘")
    parser.add_argument("--course", required=True, help="course_id，如 operating-systems")
    parser.add_argument("--lesson", required=True, help="lesson_id，如 ch3-process-scheduling")
    parser.add_argument("--source", choices=("file",), default="file",
                        help="数据源：file=ingest/sample 样例（数据库数据源已撤）")
    parser.add_argument("--video-minutes", type=int, default=0,
                        help="视频时长（分钟）。暂定：等视频接入后再填，默认 0")
    parser.add_argument("--scaffold", action="store_true",
                        help="只建目录骨架 + 默认 lesson-plan，不读数据源")
    args = parser.parse_args(argv)

    if args.scaffold:
        rel = scaffold(args.course, args.lesson)
        print(f"已建骨架：{rel}")
        print("  含 知识点.md / 本节课目标.md / 字幕.md / lesson-plan.json")
        return 0

    source = _resolve_source(args.source)
    result = ingest(args.course, args.lesson, source=source, video_minutes=args.video_minutes)
    print("整理完成：")
    for key, value in result.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
