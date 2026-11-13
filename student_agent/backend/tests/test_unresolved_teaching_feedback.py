"""A follow-up vague help request must not erase feedback about repeated teaching."""
import json

from teaching_behavior_cases import CASES, build_case
from backend.teaching import typed_state


def test_repetition_feedback_survives_followup_help_and_snapshot_reload():
    state = build_case(next(c for c in CASES if c['id'] == '02'))
    state['student_text'] = '刚才讲过的不用重复，请针对我还没掌握的部分继续。'
    feedback = '刚才讲过的不用重复'
    state = typed_state.advance(state, 'unclear', None,
        observation={'teacher_feedback': feedback})
    state = json.loads(json.dumps(state))
    state['student_text'] = '我现在还不确定，请只解释当前卡住的一步。'
    state = typed_state.advance(state, 'question', None,
        observation={'help_quote': '请只解释当前卡住的一步'})
    plan = typed_state.teaching_plan(state)
    assert plan['action'] == 'clarify'
    assert plan['unresolved_teacher_feedback'] == feedback
    assert all(r['status'] != 'demonstrated' for r in state['points'][0]['requirements'])


def test_new_learner_evidence_releases_the_earlier_feedback_constraint():
    state = build_case(next(c for c in CASES if c['id'] == '02'))
    state['student_text'] = '不要重复'
    state = typed_state.advance(state, 'unclear', None, observation={'teacher_feedback': '不要重复'})
    state['student_text'] = '下标从0开始，其他的还不知道'
    state = typed_state.advance(state, 'answer', {'answer_result': 'partial',
        'evidence': '学生说明下标起点', 'next_step': '', 'updates': [
            {'requirement_id': state['points'][0]['requirements'][0]['id'], 'status': 'demonstrated',
             'evidence': '下标从0开始', 'gap': ''}]})
    assert typed_state.teaching_plan(state)['unresolved_teacher_feedback'] == ''
