"""Contract + adapter unit tests (stdlib unittest, no network).

Run: python -m unittest discover -s tests -p "test_integration_*.py"
"""
import base64
import hashlib
import hmac
import json
import os
import time
import unittest
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "platform-learning-context-v1.json"


class CourseAdapterTests(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault("STUDENT_SERVICE_KEY", "unit-test-key")
        from apps.integration import course_adapter
        self.adapter = course_adapter
        self.payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_full_context_with_classroom(self):
        context = self.adapter.from_platform_payload(self.payload)
        self.assertEqual(context.course_title, "心理健康课")
        self.assertEqual(context.publication.version, 2)
        self.assertEqual(context.classroom.id, "sandplay-e2e-v1")
        lesson = context.lessons[0]
        self.assertEqual(len(lesson.segments), 1)
        segment = lesson.segments[0]
        self.assertEqual(segment.source_scene_id, "jOc_Iof1owSSm4bFQEcCD")
        self.assertIn("心理沙盘游戏课堂", segment.content)
        self.assertEqual(segment.completion_rule, "scene-completed")

    def test_text_only_context_without_classroom(self):
        payload = dict(self.payload)
        payload["classroom"] = None
        context = self.adapter.from_platform_payload(payload)
        self.assertIsNone(context.classroom)
        self.assertEqual(context.lessons[0].segments[0].completion_rule, "discussed")
        self.assertIn("心理沙盘", context.lessons[0].segments[0].content)

    def test_playback_grant_is_preserved_by_adapter(self):
        payload = json.loads(json.dumps(self.payload))
        payload["classroom"]["playbackToken"] = "signed-playback-grant"
        context = self.adapter.from_platform_payload(payload)
        self.assertEqual(context.classroom.playback_token, "signed-playback-grant")
        self.assertEqual(context.lessons[0].classroom.playback_token,
                         "signed-playback-grant")

    def test_unknown_schema_version_rejected(self):
        payload = dict(self.payload, schemaVersion=99)
        with self.assertRaises(self.adapter.ContextContractError):
            self.adapter.from_platform_payload(payload)

    def test_missing_required_field_rejected(self):
        payload = dict(self.payload)
        del payload["publication"]
        with self.assertRaises(self.adapter.ContextContractError):
            self.adapter.from_platform_payload(payload)

    def test_evaluation_from_entries_not_default(self):
        context = self.adapter.from_platform_payload(self.payload)
        self.assertFalse(context.evaluation.is_default)
        self.assertTrue(context.evaluation.knowledge_points)
        self.assertNotIn("操作系统", json.dumps(context.evaluation.dict(), ensure_ascii=False))

    def test_evaluation_default_fallback_marked(self):
        payload = dict(self.payload, knowledgePackage={"title": "", "summary": "", "entries": []})
        context = self.adapter.from_platform_payload(payload)
        self.assertTrue(context.evaluation.is_default)
        self.assertEqual(context.evaluation.source, "default-semantic")

    def test_generated_plan_uses_frontend_phase_contract(self):
        context = self.adapter.from_platform_payload(self.payload)
        plan = self.adapter.load_plan_for_session({"learning_context": context.model_dump()})
        self.assertEqual(plan["stages"][0]["id"], "guided_learning")

    def test_platform_plan_binds_segments_to_published_knowledge(self):
        context = self.adapter.from_platform_payload(self.payload)
        plan = self.adapter.load_plan_for_session({"learning_context": context.model_dump()})
        self.assertTrue(plan["segments"][0]["knowledge_point_ids"])
        published_ids = {item["id"] for item in plan["knowledge_points"]}
        self.assertTrue(set(plan["segments"][0]["knowledge_point_ids"]).issubset(published_ids))

    def test_tutor_prompt_and_questions_use_only_published_course(self):
        from apps.integration import prompt_context

        context = self.adapter.from_platform_payload(self.payload)
        plan = self.adapter.load_plan_for_session({"learning_context": context.model_dump()})
        state = {"lesson_plan": plan, "active_segment_id": plan["segments"][0]["id"]}
        prompt = prompt_context.tutor_context(state)
        questions = prompt_context.question_queue("recap_discussion", plan, [])
        self.assertIn(plan["title"], prompt)
        self.assertIn(plan["segments"][0]["content"], prompt)
        self.assertNotIn("操作系统", prompt)
        self.assertTrue(questions)
        self.assertTrue(all(item["source"] == "platform-published evaluation contract"
                            for item in questions))


class PlayerBridgeTests(unittest.TestCase):
    def setUp(self):
        from apps.integration import player_bridge
        self.bridge = player_bridge
        self.state = player_bridge.PlayerBridgeState(expected_classroom_id="sandplay-e2e-v1")

    def test_scene_completion_advances_once(self):
        event = self.bridge.PlayerEvent(type=self.bridge.SCENE_COMPLETED,
                                        classroom_id="sandplay-e2e-v1",
                                        scene_id="scene-1", event_id="e1")
        self.assertEqual(self.state.apply(event), "segment-advanced")
        duplicate = self.bridge.PlayerEvent(type=self.bridge.SCENE_COMPLETED,
                                            classroom_id="sandplay-e2e-v1",
                                            scene_id="scene-1", event_id="e2")
        self.assertIsNone(self.state.apply(duplicate))
        replay = self.bridge.PlayerEvent(type=self.bridge.SCENE_COMPLETED,
                                         classroom_id="sandplay-e2e-v1",
                                         scene_id="scene-1", event_id="e1")
        self.assertIsNone(self.state.apply(replay))

    def test_ended_fires_once(self):
        event = self.bridge.PlayerEvent(type=self.bridge.PLAYBACK_ENDED, event_id="end")
        self.assertEqual(self.state.apply(event), "ended")
        self.assertIsNone(self.state.apply(event))

    def test_wrong_classroom_rejected(self):
        event = self.bridge.PlayerEvent(type=self.bridge.SCENE_COMPLETED,
                                        classroom_id="other-class", scene_id="s1")
        with self.assertRaises(self.bridge.PlayerEventError):
            self.state.apply(event)

    def test_parse_rejects_unknown_and_malformed(self):
        with self.assertRaises(self.bridge.PlayerEventError):
            self.bridge.parse_message({"type": "HACKED"})
        with self.assertRaises(self.bridge.PlayerEventError):
            self.bridge.parse_message("not-a-dict")
        event = self.bridge.parse_message({"type": "PLAYER_READY", "classroomId": "sandplay-e2e-v1"})
        self.assertEqual(event.type, "PLAYER_READY")


class LaunchContextTests(unittest.TestCase):
    KEY = "unit-test-key"

    def _token(self, payload: dict) -> str:
        payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        encoded = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
        signature = hmac.new(self.KEY.encode(), payload_json.encode(), hashlib.sha256).hexdigest()
        return f"{encoded}.{signature}"

    def setUp(self):
        os.environ["STUDENT_SERVICE_KEY"] = self.KEY

    def tearDown(self):
        os.environ.pop("STUDENT_SERVICE_KEY", None)

    def test_roundtrip_and_identity(self):
        from apps.integration import launch_context
        payload = {"uid": "u1", "cid": "c1", "rid": "r1",
                   "pub": {"publicationId": "p1", "version": 3},
                   "exp": int(time.time()) + 600, "nonce": "n"}
        parsed = launch_context.verify_launch_token(self._token(payload))
        identity = launch_context.launch_identity(parsed)
        self.assertEqual(identity["userId"], "u1")
        self.assertEqual(identity["courseId"], "c1")
        self.assertEqual(identity["publicationVersion"], 3)

    def test_tamper_rejected(self):
        from apps.integration import launch_context
        token = self._token({"uid": "u1", "cid": "c1", "pub": {},
                             "exp": int(time.time()) + 600})
        with self.assertRaises(launch_context.LaunchTokenError):
            launch_context.verify_launch_token(token[:-2] + "zz")

    def test_expired_rejected(self):
        from apps.integration import launch_context
        token = self._token({"uid": "u1", "cid": "c1", "pub": {},
                             "exp": int(time.time()) - 10})
        with self.assertRaises(launch_context.LaunchTokenError):
            launch_context.verify_launch_token(token)


if __name__ == "__main__":
    unittest.main()
