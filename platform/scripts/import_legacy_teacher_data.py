"""Import legacy teacher-agent JSON course data into the unified database.

Reads the old teacher service's local data directory (courses, materials,
extractions, artifacts, jobs, classrooms, knowledge packages, knowledge
graphs, artifact files) and writes everything into the teacher schema —
the same tables the new teacher agent reads in postgres mode. Platform
registration (public.course + teacher_course_link) is created for each
imported course so enrollment and the student flow work.

Idempotent: every insert is ON CONFLICT DO UPDATE (or DO NOTHING for
binary blobs already present). Ownership is repointed to a real teacher.

Usage:
  platform/.venv/Scripts/python.exe scripts/import_legacy_teacher_data.py \
      --data-dir "E:\\...\\agent\\teacher_agent\\data" \
      --teacher lihua@qq.com \
      --courses sx2QQqfZUm48,4WDo_O9K2qOQ
"""
import argparse
import sys
import json
import uuid
from pathlib import Path

import psycopg
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def ms(value, default=1):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--teacher", required=True, help="real teacher uuid or email")
    parser.add_argument("--courses", default="", help="comma-separated course ids; default all")
    parser.add_argument("--activate-courseware", action="store_true",
                        help="publish lesson-courseware artifacts so students see the player")
    args = parser.parse_args()

    env = dotenv_values(ROOT / '.env')
    database_url = env['DATABASE_URL'].replace('+psycopg', '')
    data_dir = Path(args.data_dir)

    with psycopg.connect(database_url) as conn:
        teacher = conn.execute(
            "SELECT id::text FROM public.user WHERE (id::text=%s OR email=%s) AND role='teacher' AND is_active",
            (args.teacher, args.teacher)).fetchone()
        if not teacher:
            print(f"ERROR: teacher '{args.teacher}' not found")
            return 1
        teacher_id = teacher[0]

        course_ids = [c for c in args.courses.split(",") if c] or [
            p.stem for p in (data_dir / "course-spaces" / "courses").glob("*.json")]

        for course_id in course_ids:
            course = load_json(data_dir / "course-spaces" / "courses" / f"{course_id}.json")
            if not course:
                print(f"SKIP {course_id}: course file missing")
                continue
            course["teacherId"] = teacher_id
            now_ms = ms(course.get("updatedAt"), ms(course.get("createdAt")))

            # 1. Course row (payload keeps materials/modules/lessons inline).
            conn.execute(
                "INSERT INTO teacher.mentra_courses (id, teacher_id, status, title, payload, created_at, updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (id) DO UPDATE SET teacher_id=EXCLUDED.teacher_id, status=EXCLUDED.status, "
                "title=EXCLUDED.title, payload=EXCLUDED.payload, updated_at=EXCLUDED.updated_at",
                (course_id, teacher_id, course.get("status", "draft"), course.get("title", ""),
                 json.dumps(course, ensure_ascii=False), ms(course.get("createdAt")), now_ms))

            # 2. Material source bytes + extractions.
            materials_dir = data_dir / "course-spaces" / "materials"
            imported_materials = 0
            for material in course.get("materials", []):
                material_id = material.get("id")
                storage_key = material.get("storageKey") or f"{material_id}/source"
                file_path = materials_dir / storage_key
                if not file_path.is_file():
                    file_path = materials_dir / storage_key.split("/")[-1]
                if file_path.is_file():
                    conn.execute(
                        "INSERT INTO teacher.mentra_course_material_files "
                        "(storage_key, material_id, course_id, file_name, mime_type, size_bytes, sha256, bytes, created_at, updated_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT (storage_key) DO NOTHING",
                        (storage_key, material_id, course_id, material.get("name", "source"),
                         material.get("mimeType", "application/octet-stream"), material.get("size", 0),
                         material.get("sha256", ""), file_path.read_bytes(),
                         ms(material.get("createdAt")), ms(material.get("updatedAt"))))
                extraction = load_json(materials_dir / material_id / "extraction.json")
                if extraction:
                    conn.execute(
                        "INSERT INTO teacher.mentra_material_extractions "
                        "(material_id, course_id, source_sha256, payload, created_at, updated_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT (material_id) DO UPDATE SET payload=EXCLUDED.payload, updated_at=EXCLUDED.updated_at",
                        (material_id, course_id, extraction.get("sourceSha256", material.get("sha256", "")),
                         json.dumps(extraction, ensure_ascii=False),
                         ms(extraction.get("createdAt")), ms(extraction.get("createdAt"))))
                    imported_materials += 1
            print(f"  materials: {len(course.get('materials', []))} listed, {imported_materials} extractions")

            # 3. Jobs.
            for job_file in (data_dir / "course-spaces" / "jobs").glob("*.json"):
                job = load_json(job_file)
                if job and job.get("courseId") == course_id:
                    conn.execute(
                        "INSERT INTO teacher.mentra_artifact_jobs "
                        "(id, course_id, teacher_id, artifact_type, status, payload, created_at, updated_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT (id) DO NOTHING",
                        (job["id"], course_id, teacher_id, job.get("artifactType", "lesson-courseware"),
                         job.get("status", "queued"), json.dumps(job, ensure_ascii=False),
                         ms(job.get("createdAt")), ms(job.get("updatedAt"))))

            # 4. Artifacts (+ optional courseware activation). Keep the classroom
            # ownership map so the classroom import cannot leak records from a
            # different course when more than one legacy course is imported.
            classroom_artifacts: dict[str, str] = {}
            for artifact_file in (data_dir / "course-spaces" / "artifacts").glob("*.json"):
                artifact = load_json(artifact_file)
                if not artifact or artifact.get("courseId") != course_id:
                    continue
                if args.activate_courseware and artifact.get("type") == "lesson-courseware" \
                        and artifact.get("classroomId"):
                    artifact["status"] = "published"
                    artifact["classVisible"] = True
                    artifact.setdefault("classPublicationId", f"CLS-A-{artifact['id'][:12]}")
                    artifact["classPublishedAt"] = ms(artifact.get("updatedAt"))
                classroom_id = artifact.get("classroomId")
                if classroom_id:
                    # Legacy records used /classroom/:id. Under the unified
                    # gateway that path belongs to the platform SPA, so persist
                    # the stable teacher-player entry instead.
                    artifact["classroomUrl"] = f"/classroom-player/{classroom_id}"
                    classroom_artifacts[classroom_id] = artifact["id"]
                conn.execute(
                    "INSERT INTO teacher.mentra_course_artifacts "
                    "(id, job_id, course_id, teacher_id, artifact_type, status, payload, created_at, updated_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (id) DO UPDATE SET teacher_id=EXCLUDED.teacher_id, status=EXCLUDED.status, "
                    "payload=EXCLUDED.payload, updated_at=EXCLUDED.updated_at",
                    (artifact["id"], artifact.get("jobId", "imported"), course_id, teacher_id,
                     artifact.get("type", "lesson-courseware"), artifact.get("status", "review"),
                     json.dumps(artifact, ensure_ascii=False),
                     ms(artifact.get("createdAt")), ms(artifact.get("updatedAt"))))

            # 5. Artifact files (word exports etc.).
            files_dir = data_dir / "course-spaces" / "artifact-files"
            if files_dir.is_dir():
                for artifact_dir in files_dir.iterdir():
                    for file_path in artifact_dir.iterdir():
                        storage_key = f"{artifact_dir.name}/{file_path.name}"
                        conn.execute(
                            "INSERT INTO teacher.mentra_artifact_files "
                            "(storage_key, artifact_id, file_name, mime_type, size_bytes, sha256, bytes, created_at, updated_at) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                            "ON CONFLICT (storage_key) DO NOTHING",
                            (storage_key, artifact_dir.name, file_path.name,
                             "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                             file_path.stat().st_size, "", file_path.read_bytes(), now_ms, now_ms))

            # 6. Classrooms (scenes + stage, attached to the course). Only
            # import classrooms referenced by this course's artifacts.
            for classroom_file in (data_dir / "classrooms").glob("*.json"):
                classroom = load_json(classroom_file)
                if not classroom or classroom.get("id") not in classroom_artifacts:
                    continue
                artifact_id = classroom_artifacts[classroom["id"]]
                conn.execute(
                    "INSERT INTO teacher.mentra_classrooms "
                    "(id, course_id, artifact_id, stage, scenes, payload, created_at, updated_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (id) DO UPDATE SET course_id=EXCLUDED.course_id, "
                    "artifact_id=EXCLUDED.artifact_id, stage=EXCLUDED.stage, "
                    "scenes=EXCLUDED.scenes, payload=EXCLUDED.payload, updated_at=EXCLUDED.updated_at",
                    (classroom["id"], course_id, artifact_id,
                     json.dumps(classroom.get("stage", {}), ensure_ascii=False),
                     json.dumps(classroom.get("scenes", []), ensure_ascii=False),
                     json.dumps(classroom, ensure_ascii=False),
                     ms(classroom.get("createdAt")), ms(classroom.get("updatedAt"), ms(classroom.get("createdAt")))))

            # 7. Knowledge packages.
            for package_file in (data_dir / "course-spaces" / "knowledge-packages").glob("*.json"):
                package = load_json(package_file)
                if not package or package.get("courseId") != course_id:
                    continue
                conn.execute(
                    "INSERT INTO teacher.mentra_knowledge_packages "
                    "(id, course_id, teacher_id, version, status, payload, created_at, published_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (id) DO UPDATE SET status=EXCLUDED.status, payload=EXCLUDED.payload, "
                    "published_at=EXCLUDED.published_at",
                    (package["id"], course_id, teacher_id, ms(package.get("version"), 1),
                     package.get("status", "published"), json.dumps(package, ensure_ascii=False),
                     ms(package.get("createdAt")), ms(package.get("publishedAt"))))

            # 8. Knowledge graphs (versions + nodes + edges).
            graph_dir = data_dir / "course-spaces" / "knowledge-graphs" / course_id
            if graph_dir.is_dir():
                for graph_file in graph_dir.glob("v*.json"):
                    graph = load_json(graph_file)
                    if not graph:
                        continue
                    version = ms(graph.get("version"), 1)
                    conn.execute(
                        "INSERT INTO teacher.mentra_course_graph_versions "
                        "(course_id, version, status, title, summary, source_material_hashes, created_by, created_at, published_at) "
                        "VALUES (%s,%s,%s,%s,%s,CAST(%s AS jsonb),%s,%s,%s) "
                        "ON CONFLICT (course_id, version) DO UPDATE SET status=EXCLUDED.status, published_at=EXCLUDED.published_at",
                        (course_id, version, graph.get("status", "draft"), graph.get("title", ""),
                         graph.get("summary"), json.dumps(graph.get("sourceMaterialHashes", [])),
                         graph.get("createdBy", teacher_id), ms(graph.get("createdAt")),
                         graph.get("publishedAt")))
                    for node in graph.get("nodes", []):
                        properties = {k: v for k, v in node.items() if k not in (
                            "courseId", "graphVersion", "id", "type", "title", "description",
                            "module_id", "lesson_id", "moduleId", "lessonId", "status",
                            "createdAt", "updatedAt", "evidence")}
                        conn.execute(
                            "INSERT INTO teacher.mentra_course_graph_nodes "
                            "(course_id, graph_version, id, node_type, title, description, module_id, lesson_id, status, properties, created_at, updated_at) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,CAST(%s AS jsonb),%s,%s) "
                            "ON CONFLICT (course_id, graph_version, id) DO NOTHING",
                            (course_id, version, node.get("id"), node.get("type", "knowledge-point"),
                             node.get("title", ""), node.get("description"),
                             node.get("moduleId") or node.get("module_id"),
                             node.get("lessonId") or node.get("lesson_id"),
                             node.get("status", "approved"), json.dumps(properties, ensure_ascii=False),
                             ms(node.get("createdAt")), ms(node.get("updatedAt"))))
                        for index, evidence in enumerate(node.get("evidence") or []):
                            if not isinstance(evidence, dict):
                                continue
                            evidence_id = f"{node.get('id')}:e{index}"
                            conn.execute(
                                "INSERT INTO teacher.mentra_course_graph_evidence "
                                "(course_id, graph_version, id, node_id, material_id, chunk_id, page, slide, source_sha256, excerpt) "
                                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                                "ON CONFLICT (course_id, graph_version, id) DO NOTHING",
                                (course_id, version, evidence_id, node.get("id"),
                                 evidence.get("materialId"), evidence.get("chunkId"),
                                 evidence.get("page"), evidence.get("slide"),
                                 evidence.get("sourceSha256", ""), evidence.get("excerpt")))
                    for edge in graph.get("edges", []):
                        conn.execute(
                            "INSERT INTO teacher.mentra_course_graph_edges "
                            "(course_id, graph_version, id, source_node_id, target_node_id, relation_type, properties, created_at) "
                            "VALUES (%s,%s,%s,%s,%s,%s,CAST(%s AS jsonb),%s) "
                            "ON CONFLICT (course_id, graph_version, id) DO NOTHING",
                            (course_id, version, edge.get("id"), edge.get("sourceNodeId"),
                             edge.get("targetNodeId"), edge.get("type", "related-to"),
                             json.dumps(edge.get("properties", {}), ensure_ascii=False),
                             ms(edge.get("createdAt"))))
                    print(f"  graph v{version} ({graph.get('status')}): nodes={len(graph.get('nodes', []))}")

            # 9. Platform registration (UUID mapping via teacher_course_link).
            link = conn.execute(
                "SELECT course_id FROM teacher_course_link WHERE external_course_id=%s",
                (course_id,)).fetchone()
            if link:
                platform_id = link[0]
            else:
                platform_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO public.course (id, owner_id, title, enroll_code, description, created_at) "
                    "VALUES (%s,%s,%s,%s,%s,now())",
                    (platform_id, teacher_id, course.get("title", course_id),
                     "".join(__import__("random").choices("ABCDEFGHJKLMNPQRSTUVWXYZ23456789", k=8)),
                     course.get("description")))
                conn.execute(
                    "INSERT INTO teacher_course_link (course_id, external_course_id) VALUES (%s,%s)",
                    (platform_id, course_id))
            conn.commit()

            code = conn.execute("SELECT enroll_code FROM public.course WHERE id=%s",
                                (platform_id,)).fetchone()
            print(f"IMPORTED {course.get('title')} ({course_id}) → platform {platform_id}, "
                  f"enroll code {code[0] if code else '?'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
