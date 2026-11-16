"""Postclass navigation must move the real focus without fabricating mastery."""
from langchain_core.messages import AIMessage
from test_typed_teaching import scripted
from teaching_behavior_cases import CASES, build_case
from backend.teaching import typed_state, typed_teaching


def test_explicit_postclass_next_moves_and_persists_focus(monkeypatch):
    state = build_case(next(c for c in CASES if c['id'] == '49'))
    state['student_text'] = '现在都懂了，请进入下一个知识点'
    packet = AIMessage(content='', tool_calls=[{'name': 'submit_current_assessment', 'id': 'next',
        'args': {'intent': 'unclear', 'assessment': None,
                 'observation': {'control': 'skip', 'control_quote': '请进入下一个知识点'}}}])
    scripted(monkeypatch, packet, AIMessage(content='我们看下一个知识点。'))
    result = typed_teaching.run(state, after_class=True)
    assert typed_state.current(result, after_class=True)['id'] == state['points'][1]['id']
    assert result['current_task']['pointId'] == state['points'][1]['id']
    assert result['points'][0]['status'] != 'mastered'
    assert result['points'][0]['requirements'] == state['points'][0]['requirements']
    assert typed_state.teaching_plan(result, after_class=True)['control']['applied'] is True
    result['student_text'] = '整数、浮点数和字符'
    continued = typed_state.advance(result, 'unclear', None, after_class=True)
    assert typed_state.current(continued, after_class=True)['id'] == state['points'][1]['id']


def test_plain_continue_does_not_skip_and_last_gap_is_not_completed():
    state = build_case(next(c for c in CASES if c['id'] == '49'))
    state['student_text'] = 'ok，继续'
    result = typed_state.advance(state, 'unclear', None, after_class=True,
                                observation={'continue_quote': '继续'})
    assert typed_state.current(result, after_class=True)['id'] == state['points'][0]['id']
    result['points'][1]['status'] = 'mastered'
    result['student_text'] = '下一个知识点'
    result = typed_state.advance(result, 'unclear', None, after_class=True,
                                observation={'control': 'skip', 'control_quote': '下一个知识点'})
    assert typed_state.current(result, after_class=True)['id'] == state['points'][0]['id']
    assert typed_state.teaching_plan(result, after_class=True)['control']['applied'] is False
    assert result['transition'] != 'all_mastered'


def test_selected_focus_survives_serialization_and_mastery_returns_to_gap():
    import json
    state = build_case(next(c for c in CASES if c['id'] == '49'))
    state['student_text'] = '下一个知识点'
    result = typed_state.advance(state, 'unclear', None, after_class=True,
                                observation={'control': 'skip', 'control_quote': '下一个知识点'})
    restored = json.loads(json.dumps(result))
    assert typed_state.current(restored, after_class=True)['id'] == state['points'][1]['id']
    restored['points'][1]['status'] = 'mastered'
    assert typed_state.current(restored, after_class=True)['id'] == state['points'][0]['id']
