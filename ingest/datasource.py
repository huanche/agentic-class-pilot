"""数据源抽象层。

`DataSource` 定义最小接口：`fetch_syllabus` / `fetch_transcript`（返回原始脏数据）。

实现：
  · `FileDataSource`（本文件）—— 从 ingest/sample/ 读样例脏数据，供无库时演练/测试。
"""

from __future__ import annotations

from pathlib import Path

SAMPLE_DIR = Path(__file__).resolve().parent / "sample"


class DataSource:
    """数据源抽象接口。"""

    def fetch_syllabus(self, course_id: str, lesson_id: str) -> str | None:
        """返回原始课程大纲（脏数据）。无此课时返回 None。"""
        raise NotImplementedError

    def fetch_transcript(self, course_id: str, lesson_id: str) -> str | None:
        """返回原始字幕（脏数据）。无字幕返回 None。"""
        raise NotImplementedError


class FileDataSource(DataSource):
    """临时数据源：从 ingest/sample/<course_id>/<lesson_id>/ 读样例脏数据。

    样例目录结构：
        ingest/sample/<course_id>/<lesson_id>/syllabus.txt   # 原始大纲
        ingest/sample/<course_id>/<lesson_id>/transcript.srt # 原始字幕
    """

    def _read(self, course_id: str, lesson_id: str, name: str) -> str | None:
        path = SAMPLE_DIR / course_id / lesson_id / name
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    def fetch_syllabus(self, course_id: str, lesson_id: str) -> str | None:
        return self._read(course_id, lesson_id, "syllabus.txt")

    def fetch_transcript(self, course_id: str, lesson_id: str) -> str | None:
        return self._read(course_id, lesson_id, "transcript.srt")
