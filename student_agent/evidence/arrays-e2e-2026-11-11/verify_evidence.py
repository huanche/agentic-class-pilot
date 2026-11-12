"""Check recorded observations without replaying any mutating request."""
import json
from pathlib import Path

folder = Path(__file__).parent
def read(name):
    return json.loads((folder / f'{name}.json').read_text(encoding='utf-8'))

before = read('snapshot-turn04')['dialogue']['points']
after = read('snapshot-turn05')['dialogue']['points']
checks = {
    'main_four_mastered': read('final-feedback')['counts'] == {'mastered': 4, 'needs_review': 0, 'not_assessed': 0},
    'question_does_not_change_requirements': [(p['id'], p['requirements']) for p in before] == [(p['id'], p['requirements']) for p in after],
    'duplicate_keeps_version': read('idempotency')['unchangedVersion'],
    'duplicate_keeps_dialogue': read('idempotency')['unchangedDialogue'],
    'empty_answer_rejected_without_change': read('empty-answer-check')['status'] == 422 and read('empty-answer-check')['stateUnchanged'],
    'resume_same_session_messages_task': all(read('resume-midlesson')[key] for key in ['sameSession', 'sameMessages', 'sameTask']),
    'all_mastered_no_new_messages': read('view-finished')['messages'] == read('view-all-mastered-entry')['messages'],
    'early_exit_preserves_unassessed': read('early-feedback')['counts'] == {'mastered': 0, 'needs_review': 1, 'not_assessed': 3},
    'postclass_updates_only_completed_point': read('early-final-feedback')['counts'] == {'mastered': 1, 'needs_review': 0, 'not_assessed': 3},
    'postclass_repeated_original_question_observed': read('early-task-check')['sameOriginalQuestion'],
}
result = {'checks': checks, 'allRecordedClaimsSupported': all(checks.values())}
(folder / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
assert result['allRecordedClaimsSupported']
