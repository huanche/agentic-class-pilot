"""Grounded platform question generation regressions; no external model required."""
import json
import unittest
from unittest.mock import Mock, patch

from apps.integration import course_adapter, prompt_context


class GroundedQuestionTests(unittest.TestCase):
    def setUp(self):
        self.evidence = "电路交换在通信前建立专用连接，通信期间双方独占所分配的资源。"
        self.payload = {
            "schemaVersion": 1, "userId": "u", "courseId": "c",
            "courseTitle": "现代交换原理", "publication": {"id": "p", "version": 1},
            "knowledgePackage": {"entries": [{"id": "entry-1",
                "title": "课件生成 / 第1周｜习题与答案",
                "content": "# 第1周《现代交换原理》分层习题与答案\n## 一、基础巩固层\n### 1. 填空题\n" + self.evidence}],
                # 旧复述/探究出题链路的测试需要目录非空——补一份 rubric 让
                # evaluation 有知识点（目录来源已由知识点工件接管，这里只保链路可测）
                "rubric": {"knowledgePoints": [{"id": "entry-1", "title": "电路交换",
                                                "expectedConcepts": ["独占资源"]}]}
            },
        }
        context = course_adapter.from_platform_payload(self.payload)
        self.plan = course_adapter.load_plan_for_session({"learning_context": context.model_dump()})

    def response(self, **overrides):
        item = {"kp_id": "entry-1", "source_id": "entry-1", "evidence": self.evidence,
                "question": "电路交换为什么需要在通信前建立连接？"}
        item.update(overrides)
        return json.dumps({"questions": [item]}, ensure_ascii=False)

    def test_preserves_database_body_and_ignores_structural_headings(self):
        self.assertIn(self.evidence, self.plan["knowledge_sources"][0]["content"])
        expected = self.plan["knowledge_points"][0]["expected"]
        self.assertNotIn("一、基础巩固层", expected)
        self.assertIn(self.evidence, prompt_context.tutor_context({"lesson_plan": self.plan}))

    def test_model_receives_outline_and_current_lesson_with_phase(self):
        generate = Mock(return_value=self.response())
        for phase in ("recap_discussion", "deep_inquiry"):
            queue = prompt_context.question_queue(phase, self.plan, ["entry-1"], generate=generate)
            self.assertEqual(queue[0]["question"], "电路交换为什么需要在通信前建立连接？")
            self.assertEqual(queue[0]["evidence"], self.evidence)
            payload = json.loads(generate.call_args.args[1])
            self.assertEqual(payload["phase"], phase)
            self.assertEqual(payload["unresolved"], ["entry-1"])
            self.assertIn(self.evidence, payload["knowledgeOutline"][0]["content"])

    def test_rejects_hallucinated_ids_evidence_and_heading_questions(self):
        for response in ("invalid", "[]", self.response(kp_id="other-course"),
                         self.response(evidence="正文没有提过的虚构知识点"),
                         self.response(question="请说明基础巩固层的核心内容？")):
            with self.subTest(response=response):
                queue = prompt_context.question_queue("recap_discussion", self.plan, [],
                                                       generate=Mock(return_value=response))
                self.assertIn(self.evidence, queue[0]["question"])
                self.assertNotIn("AI-generated", queue[0]["source"])

    def test_rubric_survives_platform_adapter(self):
        self.payload["knowledgePackage"]["rubric"] = {"knowledgePoints": [
            {"id": "circuit", "title": "电路交换", "expectedConcepts": ["独占资源"]}]}
        context = course_adapter.from_platform_payload(self.payload)
        self.assertEqual(context.evaluation.source, "published-rubric")
        self.assertEqual(context.evaluation.knowledge_points[0].id, "circuit")

    def test_large_context_remains_valid_json(self):
        self.plan["segments"] = [{"id": "long", "title": "电路交换", "content": self.evidence * 1000}]
        result = prompt_context.tutor_context({"lesson_plan": self.plan, "active_segment_id": "long"})
        self.assertLessEqual(len(result), 12000)
        self.assertEqual(json.loads(result)["currentSegment"]["id"], "long")

    def test_retrieval_prioritizes_selected_lesson_not_first_document(self):
        self.plan["title"] = "分组交换"
        self.plan["segments"] = [{"id": "packet", "title": "分组交换", "content": "分组交换共享链路"}]
        self.plan["knowledge_sources"].append({"id": "entry-2", "title": "第二周",
                                             "content": "分组交换共享链路，数据分组传输。"})
        self.assertEqual(prompt_context.lesson_sources(self.plan)[0]["id"], "entry-2")

    def test_orchestrator_uses_generation_and_never_local_course_fallback(self):
        """复述/探究出题：只用平台发布内容，永不回退本地旧课程题库。"""
        from orchestrator import agent
        with patch.object(agent, "llm_chat", return_value=self.response()) as model:
            queue = agent.build_question_queue("deep_inquiry", [], plan=self.plan)
            model.assert_called_once()
            self.assertIn("AI-generated", queue[0]["source"])
        # 无平台计划（无知识点目录）→ 空队列，不碰本地题库
        # （旧符号 _parse_kb_questions 已随目录来源重构删除；空队列即「不兜底」）
        self.assertEqual(agent.build_question_queue("recap_discussion", [],
                         plan={"source": "platform-published"}), [])


if __name__ == "__main__":
    unittest.main()
