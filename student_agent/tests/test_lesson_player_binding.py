"""Regression: selecting lesson B must not return the course default player A."""
import ast
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
SOURCE = Path(__file__).parents[1] / 'apps/server.py'
node = next(n for n in ast.parse(SOURCE.read_text(encoding='utf-8')).body if isinstance(n, ast.FunctionDef) and n.name == 'session_lesson')
node.decorator_list = []
class HttpError(Exception):
    def __init__(self, **kwargs): self.status_code = kwargs['status_code']
def classroom(cid): return SimpleNamespace(id=cid, player_url='/player/'+cid)
def lesson(lid, video, order): return SimpleNamespace(id=lid, title=lid, order=order, week=order, lesson_number=1, classroom=classroom(video) if video else None, segments=[])
class LessonPlayerBindingTests(unittest.TestCase):
    def setUp(self):
        context = SimpleNamespace(course_title='课程', classroom=classroom('v1'), lessons=[lesson('l1','v1',1),lesson('l2','v2',2),lesson('l3',None,3)], knowledge_package=SimpleNamespace(summary=''), evaluation=SimpleNamespace(knowledge_points=[]))
        self.ns = {'_preload_disk_sessions': lambda: None, '_REGISTRY_LOCK': threading.RLock(), 'SESSIONS': {'s': {'state': {'learning_context': context}}}, 'HTTPException': HttpError}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec'), self.ns)
    def test_selected_lesson_uses_its_own_player(self):
        context = self.ns['SESSIONS']['s']['state']['learning_context']
        context.selected_lesson_id = 'l1'
        first = self.ns['session_lesson']('l1','s')
        context.selected_lesson_id = 'l2'
        second = self.ns['session_lesson']('l2','s')
        self.assertEqual(first['playerUrl'], '/player/v1'); self.assertEqual(second['playerUrl'], '/player/v2')
        self.assertNotEqual(first['classroomId'], second['classroomId'])
    def test_missing_lesson_player_does_not_fall_back_to_course_default(self):
        self.ns['SESSIONS']['s']['state']['learning_context'].selected_lesson_id = 'l3'
        result = self.ns['session_lesson']('l3','s')
        self.assertIsNone(result['classroomId']); self.assertEqual(result['playerUrl'], '')
    def test_unknown_lesson_is_rejected(self):
        self.ns['SESSIONS']['s']['state']['learning_context'].selected_lesson_id = 'l1'
        with self.assertRaises(HttpError): self.ns['session_lesson']('unknown','s')
if __name__ == '__main__': unittest.main()
