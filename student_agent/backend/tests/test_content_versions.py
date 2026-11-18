"""Immutable content, pinned sessions and publication worker fencing on PostgreSQL."""

from backend.infrastructure import content_store
from copy import deepcopy
import json

import pytest

from backend.content import lesson_content
from backend.infrastructure import persistence
from backend.infrastructure import published_knowledge
from backend.content.context import classroom_materials
from backend.content.knowledge import KnowledgeResult
from backend.teaching import service as teaching
from backend.session import service as learning_session

QUOTE = "平均数由全部数据的总和除以数据个数得到。"
ALTERNATIVE = "平均数受每个数据的取值影响。"


def point(quote=QUOTE):
    return {"id": "p", "title": "平均数", "content": quote, "sourceIds": ["scene:one"]}


def register(pg, *, compiler=None, status="ready", revision="rev"):
    scenes = [{"id": "one", "title": "平均数", "visibleText": [QUOTE, ALTERNATIVE], "actions": []}]
    with pg() as connection:
        connection.execute("INSERT INTO student.published_lesson_knowledge "
            "(course_id,lesson_id,video_revision,classroom_id,extractor_hash,scenes,points,coverage,status) "
            "VALUES ('course','lesson',%s,'room',%s,%s,%s,%s,%s)",
            (revision, compiler or published_knowledge.EXTRACTOR_HASH, json.dumps(scenes),
             json.dumps([point()]) if status == "ready" else None, json.dumps({"acceptedCount": 1}), status))
    return scenes


def session(body, *, sid="learner", user="student"):
    return {"id": sid, "context": {"userId": user, "courseId": "course", "publication": {"id": "pub", "version": 1}},
            "lessonId": "lesson", "classroomId": "room", "videoRevision": "rev", "courses": [],
            "phase": "video", "messages": [], "dialogue": teaching.new_dialogue(body["points"]),
            "contentRef": lesson_content.reference(body), "lessonContent": body, "preparation": "ready"}


def test_ready_content_is_shared_with_exact_sources_and_no_new_model_call(pg, monkeypatch):
    register(pg)
    monkeypatch.setattr(published_knowledge, "learning_points", lambda *args, **kwargs: pytest.fail("ready content must not call model"))
    first = published_knowledge.read("course", "lesson", "rev")
    body = first["contentModel"]
    assert body["validationStatus"] == "source_checked"
    assert body["topics"][0]["sourceRefs"][0]["quote"] == QUOTE
    assert first["contentRef"] == published_knowledge.read("course", "lesson", "rev")["contentRef"]
    assert not published_knowledge.process_next()
    for user in ("a", "b"):
        persistence.save(session(body, sid=user, user=user), 0)
    with pg() as connection:
        assert connection.execute("SELECT count(*) FROM student.lesson_content_versions").fetchone() == (1,)
        assert connection.execute("SELECT count(DISTINCT content_id) FROM student.student_sessions").fetchone() == (1,)


def test_compiler_upgrade_keeps_existing_sessions_on_their_original_version(pg, monkeypatch):
    register(pg)
    original = published_knowledge.read("course", "lesson", "rev")["contentModel"]
    persistence.save(session(original), 0)
    monkeypatch.setattr(published_knowledge, "EXTRACTOR_HASH", "new-extractor")
    assert published_knowledge.read("course", "lesson", "rev")["status"] == "pending"
    monkeypatch.setattr(published_knowledge, "learning_points", lambda *args, **kwargs: KnowledgeResult([point(ALTERNATIVE)], candidate_count=1))
    assert published_knowledge.process_next()
    latest = published_knowledge.read("course", "lesson", "rev")["contentModel"]
    assert latest["contentId"] != original["contentId"]
    assert latest["sourceManifestHash"] == original["sourceManifestHash"]
    old_session = persistence.restore("learner")
    assert old_session["contentRef"]["contentId"] == original["contentId"]
    assert old_session["dialogue"]["points"][0]["content"] == QUOTE
    monkeypatch.setattr(published_knowledge, "read", lambda *args, **kwargs: pytest.fail("pinned session must not upgrade"))
    learning_session.upgrade_curriculum(old_session)
    persistence.save(session(latest, sid="new-learner"), 0)
    with pg() as connection:
        assert connection.execute("SELECT count(*) FROM student.lesson_content_versions").fetchone() == (2,)


def test_an_existing_compiler_version_cannot_be_overwritten(pg):
    scenes = register(pg)
    original = published_knowledge.read("course", "lesson", "rev")["contentModel"]
    changed = lesson_content.build("course", "lesson", "rev", original["compilerVersion"],
                                   [point(ALTERNATIVE)], classroom_materials(scenes), coverage=original["coverage"])
    with pytest.raises(ValueError):
        content_store.store(changed)
    assert content_store.hydrate(session(original))["lessonContent"] == original


@pytest.mark.parametrize("lost", ["claim", "lease"])
def test_preparation_does_not_publish_results_after_losing_ownership(pg, monkeypatch, lost):
    register(pg, status="pending")
    def extract(*args, **kwargs):
        with pg() as connection:
            if lost == "claim":
                connection.execute("UPDATE student.published_lesson_knowledge SET claim_token='new-worker'")
            else:
                connection.execute("UPDATE student.published_lesson_knowledge SET lease_until=now()-interval '1 second'")
        return KnowledgeResult([point()], candidate_count=1)
    monkeypatch.setattr(published_knowledge, "learning_points", extract)
    assert published_knowledge.process_next()
    with pg() as connection:
        assert connection.execute("SELECT count(*) FROM student.lesson_content_versions").fetchone() == (0,)
        assert connection.execute("SELECT status FROM student.published_lesson_knowledge").fetchone() == ("running",)


def test_failed_new_preparation_and_retry_do_not_damage_old_content(pg, monkeypatch):
    register(pg)
    original = published_knowledge.read("course", "lesson", "rev")["contentModel"]
    monkeypatch.setattr(published_knowledge, "EXTRACTOR_HASH", "retry-compiler")
    assert published_knowledge.read("course", "lesson", "rev")["status"] == "pending"
    def fail(*args, **kwargs):
        raise TimeoutError("isolated extraction timeout")
    monkeypatch.setattr(published_knowledge, "learning_points", fail)
    assert published_knowledge.process_next()
    assert published_knowledge.read("course", "lesson", "rev")["status"] == "failed"
    assert content_store.hydrate(session(original))["lessonContent"] == original
    assert published_knowledge.retry("course", "lesson", "rev")
    monkeypatch.setattr(published_knowledge, "learning_points", lambda *args, **kwargs: KnowledgeResult([point(ALTERNATIVE)], candidate_count=1))
    assert published_knowledge.process_next()
    assert published_knowledge.read("course", "lesson", "rev")["contentRef"]["contentId"] != original["contentId"]


def test_worker_result_is_tagged_with_the_compiler_that_started_it(pg, monkeypatch):
    register(pg, status="pending")
    started = published_knowledge.EXTRACTOR_HASH
    def extract(*args, **kwargs):
        monkeypatch.setattr(published_knowledge, "EXTRACTOR_HASH", "next-deployment")
        return KnowledgeResult([point()], candidate_count=1)
    monkeypatch.setattr(published_knowledge, "learning_points", extract)
    assert published_knowledge.process_next()
    with pg() as connection:
        compiler = connection.execute("SELECT compiler_version FROM student.lesson_content_versions").fetchone()[0]
    assert compiler.endswith(started)
    assert published_knowledge.read("course", "lesson", "rev")["status"] == "pending"


def test_visual_or_missing_sources_are_reported_as_limitations():
    scenes = [{"id": "one", "visibleText": [QUOTE], "content": {"canvas": {"elements": [{"type": "image"}]}}}]
    body = lesson_content.build("course", "lesson", "rev", "compiler", [point()], classroom_materials(scenes), scenes=scenes)
    assert {"code": "visual_content_not_interpreted"} in body["coverageGaps"]
    assert body["inputCapabilities"]["originalPpt"] is False
    legacy = lesson_content.build("course", "lesson", "rev", "unknown", [point()], [])
    assert legacy["validationStatus"] == "limited" and legacy["topics"][0]["sourceRefs"] == []

@pytest.mark.parametrize('schema', [1, 2, 3])
@pytest.mark.parametrize('path', ['read', 'worker'])
@pytest.mark.parametrize('old_name,new_name', [(None, '课程'), ('课程', ''), ('课程', None), ('旧名', '新名')])
def test_course_name_metadata_reuses_immutable_archive(pg, monkeypatch, path, old_name, new_name, schema):
    register(pg)
    with pg() as c:
        if schema != 1:
            p = point()
            if schema == 2:
                p.update(type='memory', details={'statement': QUOTE, 'requiredElements': [QUOTE]})
            else:
                p.update(name=p['title'], explanation=QUOTE)
            c.execute('UPDATE student.published_lesson_knowledge SET points=%s::jsonb', (json.dumps([p]),))
        if old_name is not None:
            c.execute("UPDATE student.published_lesson_knowledge SET coverage=coverage || %s::jsonb", (json.dumps({'courseName': old_name}),))
    original = published_knowledge.read('course', 'lesson', 'rev')['contentModel']
    persistence.save(session(original), 0)
    with pg() as c:
        c.execute("UPDATE student.published_lesson_knowledge SET coverage=(coverage - 'courseName') || %s::jsonb,status='pending'", (json.dumps({'courseName': new_name}),))
    monkeypatch.setattr(published_knowledge, 'learning_points', lambda *a, **k: pytest.fail('must reuse without model'))
    for _ in range(2):
        if path == 'worker':
            published_knowledge.process_next()
        assert published_knowledge.read('course', 'lesson', 'rev')['contentModel'] == original
    assert persistence.restore('learner')['contentRef'] == lesson_content.reference(original)
    with pg() as c:
        assert c.execute('SELECT payload FROM student.lesson_content_versions').fetchall() == [(original,)]

@pytest.mark.parametrize('field,value', [('acceptedCount', 2), ('scope', 'changed')])
def test_archive_reuse_rejects_non_whitelisted_coverage(pg, field, value):
    register(pg)
    original = published_knowledge.read('course', 'lesson', 'rev')['contentModel']
    with pg() as c:
        c.execute('UPDATE student.published_lesson_knowledge SET coverage=coverage || %s::jsonb,status=\'pending\'', (json.dumps({field: value}),))
    assert published_knowledge.read('course', 'lesson', 'rev')['error'] == 'published_content_conflict'
    assert published_knowledge.process_next()
    assert published_knowledge.read('course', 'lesson', 'rev')['status'] == 'failed'
    with pg() as c:
        assert c.execute('SELECT payload FROM student.lesson_content_versions').fetchall() == [(original,)]


def test_duplicate_enqueue_and_concurrent_read_worker(pg, monkeypatch):
    from backend.internal_platform import PublishedLessonKnowledgeRequest, enqueue_published_lesson_knowledge
    from concurrent.futures import ThreadPoolExecutor
    revision = 'a' * 64
    scenes = register(pg, revision=revision)
    original = published_knowledge.read('course', 'lesson', revision)['contentModel']
    request = PublishedLessonKnowledgeRequest(courseId='course', lessonId='lesson', videoRevision=revision, classroomId='room', scenes=scenes, courseName='Course')
    for _ in range(2):
        enqueue_published_lesson_knowledge(request, 'isolated-command-test-key')
    with pg() as c:
        c.execute("UPDATE student.published_lesson_knowledge SET status='pending'")
    monkeypatch.setattr(published_knowledge, 'learning_points', lambda *a, **k: pytest.fail('no extraction'))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda n: published_knowledge.process_next() if n % 2 else published_knowledge.read('course','lesson',revision), range(8)))
    assert published_knowledge.read('course','lesson',revision)['contentModel'] == original


def test_session_sync_reports_conflict_and_recovers_without_rebinding_history(pg):
    register(pg)
    original = published_knowledge.read('course', 'lesson', 'rev')['contentModel']
    pinned = session(original)
    before = deepcopy(pinned)
    pending = {'id': 'waiting', 'context': {'courseId': 'course'}, 'phase': 'video',
               'lessonId': 'lesson', 'videoRevision': 'rev', 'dialogue': None}
    with pg() as c:
        c.execute("UPDATE student.published_lesson_knowledge SET coverage=coverage || '{\"acceptedCount\":2}'::jsonb")
    learning_session.sync_published_preparation(pending, persist=False)
    assert pending['preparation'] == 'error'
    assert pending['preparationErrorCode'] == 'published_content_conflict'
    learning_session.sync_published_preparation(pinned, persist=False)
    assert pinned == before
    with pg() as c:
        c.execute("UPDATE student.published_lesson_knowledge SET coverage=coverage || '{\"acceptedCount\":1,\"courseName\":\"Recovered\"}'::jsonb")
    learning_session.sync_published_preparation(pending, persist=False)
    assert pending['preparation'] == 'ready'
    assert pending['contentRef'] == lesson_content.reference(original)
