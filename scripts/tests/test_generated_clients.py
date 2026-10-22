"""Real generated SDKs, fake transport only: never imports app settings or DB."""
import asyncio
import copy
import importlib
import json
from pathlib import Path
import sys
import unittest
from uuid import UUID

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'contracts/generated/python'))

from student_platform_api.client import AuthenticatedClient
from student_platform_api.api.default import authorize_student_request, get_user_model_config
from student_platform_api.models.authorize_student_request_body import AuthorizeStudentRequestBody
from student_platform_api.models.platform_learning_context_v1 import PlatformLearningContextV1
from student_platform_api.types import UNSET
from student_platform_api.errors import UnexpectedStatus
from platform_teacher_api.client import AuthenticatedClient as TeacherClient
from platform_teacher_api.api.default import provision_teacher_course, update_teacher_student_state
from platform_teacher_api.models.provision_teacher_course_body import ProvisionTeacherCourseBody
from platform_teacher_api.models.student_learning_state import StudentLearningState

USER_ID = UUID('11223344-1122-3344-5566-112233445566')


def student_client(handler, **kwargs):
    return AuthenticatedClient(
        base_url='http://platform.invalid/api/v1', token='fixture-student-key',
        prefix='', auth_header_name='X-Student-Service-Key',
        timeout=httpx.Timeout(5), follow_redirects=False,
        httpx_args={'transport': httpx.MockTransport(handler), 'trust_env': False},
        **kwargs,
    )


class GeneratedPythonTests(unittest.TestCase):
    def test_all_generated_modules_import_on_supported_python(self):
        directory = ROOT / 'contracts/generated/python'
        for path in directory.rglob('*.py'):
            module = '.'.join(path.relative_to(directory).with_suffix('').parts)
            if module.endswith('.__init__'):
                module = module.removesuffix('.__init__')
            with self.subTest(module=module):
                importlib.import_module(module)

    def test_authorize_headers_body_optional_null_and_extra_response_fields(self):
        calls = []
        def handler(request):
            calls.append(request)
            self.assertEqual(request.method, 'POST')
            self.assertEqual(request.url.path, '/api/v1/internal/student/authorize')
            self.assertEqual(request.headers['X-Student-Service-Key'], 'fixture-student-key')
            self.assertNotIn('Authorization', request.headers)
            self.assertEqual(json.loads(request.content), {'cookie': None, 'launch_token': 'fixture-token'})
            self.assertEqual(request.extensions['timeout']['read'], 5)
            return httpx.Response(200, json={'userId': str(USER_ID), 'source': 'session', 'future': {'enabled': True}})

        with student_client(handler) as client:
            result = authorize_student_request.sync_detailed(
                client=client, body=AuthorizeStudentRequestBody(cookie=None, launch_token='fixture-token'))
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.parsed.user_id, USER_ID)
        self.assertEqual(result.parsed['future'], {'enabled': True})

    def test_context_fixture_keeps_missing_empty_and_unknown_fields(self):
        original = json.loads((ROOT / 'student_agent/tests/fixtures/platform-learning-context-v1.json').read_text(encoding='utf-8'))
        for lessons in (UNSET, []):
            payload = copy.deepcopy(original)
            payload.pop('lessons', None)
            if lessons is not UNSET:
                payload['lessons'] = lessons
            payload['future'] = {'enabled': True}
            model = PlatformLearningContextV1.from_dict(payload)
            self.assertEqual(model.lessons, lessons)
            point = model.knowledge_package.rubric.knowledge_points[0]
            self.assertEqual(point.title, '心理沙盘游戏初识')
            self.assertEqual(point.expected_concepts, ['认识心理沙盘游戏的组成', '了解其作用', '体验准备'])
            encoded = model.to_dict()
            self.assertEqual(encoded, payload)

    def test_error_detail_is_not_confused_with_success_and_no_redirect(self):
        for status in (401, 403, 503, 500, 307):
            calls = []
            def handler(request):
                calls.append(request)
                return httpx.Response(status, json={'detail': 'fixture'}, headers={'location': 'http://other.invalid'})
            with self.subTest(status=status), student_client(handler) as client:
                result = authorize_student_request.sync_detailed(client=client, body=AuthorizeStudentRequestBody())
                self.assertEqual(result.status_code, status)
                self.assertIsNone(result.parsed)
                self.assertEqual(json.loads(result.content), {'detail': 'fixture'})
                self.assertEqual(len(calls), 1)

    def test_unexpected_status_can_be_strict(self):
        with student_client(lambda _: httpx.Response(500), raise_on_unexpected_status=True) as client:
            with self.assertRaises(UnexpectedStatus):
                authorize_student_request.sync_detailed(client=client, body=AuthorizeStudentRequestBody())

    def test_transport_timeout_propagates_without_retry_or_real_io(self):
        calls = []
        def handler(request):
            calls.append(request)
            raise httpx.ReadTimeout('fixture timeout', request=request)
        with student_client(handler) as client:
            with self.assertRaises(httpx.ReadTimeout):
                authorize_student_request.sync_detailed(client=client, body=AuthorizeStudentRequestBody())
        self.assertEqual(len(calls), 1)

    def test_async_shared_model_configuration(self):
        def handler(request):
            self.assertEqual(request.url.path, f'/api/v1/internal/user/{USER_ID}/model-config')
            self.assertEqual(request.headers['X-Student-Service-Key'], 'fixture-student-key')
            return httpx.Response(200, json={'fixture-provider': {'model': 'fixture-model'}})
        async def scenario():
            async with student_client(handler) as client:
                result = await get_user_model_config.asyncio_detailed(USER_ID, client=client)
                self.assertEqual(result.parsed.to_dict(), {'fixture-provider': {'model': 'fixture-model'}})
        asyncio.run(scenario())

    def test_platform_teacher_write_payloads_mock_only_and_single_request(self):
        for operation, success_status in (('provision', 200), ('provision', 201), ('progress', 200)):
            calls = []
            def handler(request):
                calls.append(request)
                self.assertEqual(request.headers['X-Platform-Service-Key'], 'fixture-platform-key')
                self.assertEqual(request.headers['X-Platform-Subject'], str(USER_ID))
                self.assertNotIn('Authorization', request.headers)
                body = json.loads(request.content)
                if operation == 'provision':
                    self.assertEqual(request.method, 'POST')
                    self.assertEqual(request.url.path, '/api/course-space')
                    self.assertEqual(body, {'id': 'course-fixture', 'title': 'Fixture', 'description': None})
                    return httpx.Response(success_status, json={'success': True, 'course': {'id': 'course-fixture'}})
                self.assertEqual(request.method, 'PUT')
                self.assertEqual(request.url.path, '/api/classes/course-fixture/students')
                self.assertEqual(body['completedResourceIds'], [])
                return httpx.Response(200, json={'success': True, 'student': body, 'studentCount': 1})
            with self.subTest(operation=operation, status=success_status), TeacherClient(
                base_url='http://teacher.invalid', token='fixture-platform-key', prefix='',
                auth_header_name='X-Platform-Service-Key', headers={'X-Platform-Subject': str(USER_ID)},
                httpx_args={'transport': httpx.MockTransport(handler), 'trust_env': False},
            ) as client:
                if operation == 'provision':
                    result = provision_teacher_course.sync_detailed(client=client, body=ProvisionTeacherCourseBody(
                        id='course-fixture', title='Fixture', description=None))
                else:
                    result = update_teacher_student_state.sync_detailed('course-fixture', client=client,
                        body=StudentLearningState.from_dict({'studentId': str(USER_ID), 'name': 'Fixture',
                            'status': 'learning', 'completedResourceIds': [], 'progress': 0}))
                self.assertTrue(result.parsed.success)
                self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
