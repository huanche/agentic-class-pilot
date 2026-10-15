"""Exercise the real lesson projection with a fake SQL session (no database)."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
import uuid
SOURCE = Path(__file__).parents[2] / 'app/api/routes/student_bridge.py'
node = next(n for n in ast.parse(SOURCE.read_text(encoding='utf-8')).body if isinstance(n, ast.FunctionDef) and n.name == '_published_lessons')
ns = {'SessionDep': object, 'uuid': uuid, 'text': lambda value: value,
      '_classroom_view': lambda session, cid: {'id': cid, 'playerUrl': '/player/'+cid},
      '_issue_playback_grant': lambda *args: 'token'}
exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec'), ns)
class Session:
    def __init__(self, artifacts): self.artifacts = artifacts
    def execute(self, sql, params):
        course = {'modules': [{'lessons': [{'id': 'l1', 'title': '第1周', 'order': 1}, {'id': 'l2', 'title': '第2周', 'order': 2}]}]}
        return SimpleNamespace(first=lambda: (course,), all=lambda: [(item,) for item in self.artifacts])
def artifact(aid, lesson, classroom, week):
    return {'id': aid, 'classroomId': classroom, 'scope': {'type': 'lesson', 'lessonId': lesson},
            'publicationPlacement': {'lessonId': lesson, 'week': week, 'lessonNumber': 1, 'teachingHours': 2}}
class LessonPublicationTests(unittest.TestCase):
    def test_two_lessons_keep_distinct_classrooms(self):
        result = ns['_published_lessons'](Session([artifact('a2','l2','v2',2), artifact('a1','l1','v1',1)]), uuid.UUID(int=1), uuid.UUID(int=2))
        self.assertEqual([(item['id'], item['classroom']['id'], item['week']) for item in result], [('l1','v1',1),('l2','v2',2)])
    def test_latest_version_is_selected_only_within_its_lesson(self):
        result = ns['_published_lessons'](Session([artifact('new','l1','new-video',1), artifact('old','l1','old-video',1), artifact('a2','l2','v2',2)]), uuid.UUID(int=1), uuid.UUID(int=2))
        self.assertEqual([item['classroom']['id'] for item in result], ['new-video','v2'])
    def test_unassigned_coursewide_video_is_not_used_for_a_lesson(self):
        result = ns['_published_lessons'](Session([{'id':'a','scope':{'type':'course'},'classroomId':'ambiguous'}]), uuid.UUID(int=1), uuid.UUID(int=2))
        self.assertEqual(result, [])
if __name__ == '__main__': unittest.main()
