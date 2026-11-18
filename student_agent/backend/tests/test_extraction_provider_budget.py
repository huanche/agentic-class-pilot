"""Exercise the real OpenAI-compatible adapter at its outbound HTTP boundary."""
from copy import deepcopy
import json

import httpx
from langchain_openai import ChatOpenAI

from backend.content import knowledge
from backend.infrastructure import model
from test_typed_knowledge import MEMORY, MATERIALS


def test_deepseek_receives_native_output_budget_and_a_complete_large_tool_submission(monkeypatch):
    monkeypatch.setenv('STUDENT_AGENT_API_KEY', 'offline-budget-test')
    monkeypatch.setenv('STUDENT_AGENT_BASE_URL', 'https://api.deepseek.com/v1')
    monkeypatch.setenv('STUDENT_AGENT_MODEL', 'deepseek-v4-flash')
    points = [{**deepcopy(MEMORY), 'title': f'知识点 {i}'} for i in range(42)]
    requests = []

    def provider(request):
        body = json.loads(request.content)
        requests.append(body)
        enough = body.get('max_tokens', 8192) >= 32768
        arguments = json.dumps({'points': points}, ensure_ascii=False) if enough else '{"points":[{"title":"未完成'
        return httpx.Response(200, request=request, json={'id': 'budget-test', 'object': 'chat.completion',
            'created': 1, 'model': 'deepseek-v4-flash', 'choices': [{'index': 0,
                'finish_reason': 'tool_calls' if enough else 'length', 'message': {'role': 'assistant',
                    'content': None, 'tool_calls': [{'id': 'submit', 'type': 'function',
                        'function': {'name': 'submit_knowledge_points', 'arguments': arguments}}]}}]})

    def client(**kwargs):
        return ChatOpenAI(api_key='offline-budget-test', base_url='https://api.deepseek.com/v1',
            model='deepseek-v4-flash', max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(provider)))
    monkeypatch.setattr(model, '_model', client)
    result = knowledge.learning_points(MATERIALS)
    assert len(result.points) == 42 and result.model_calls == 1
    assert len(requests) == 1
    assert requests[0]['max_tokens'] == 32768
    assert 'max_completion_tokens' not in requests[0]
    assert requests[0]['thinking'] == {'type': 'disabled'}
    # The factory is shared, but ordinary classroom turns keep their old limits.
    teacher = model.teaching_model()
    assert teacher.max_tokens is None and 'max_tokens' not in teacher.extra_body
