"""Summarize the latest completed browser test from private, bounded telemetry."""
from collections import Counter
from pathlib import Path
import argparse
import json
import re


def analyze(log_path, sample_path, started_at=None):
    sample = json.loads(sample_path.read_text(encoding='utf8'))
    unique = {}
    for line in log_path.read_text(encoding='utf8').splitlines():
        for event in json.loads(line)['events']:
            unique[json.dumps(event, sort_keys=True)] = event
    events = sorted(unique.values(), key=lambda e: e['at'])
    completions = [e for e in events if e['event'] == 'playback-complete' and
                   (started_at is None or e['at'] >= started_at)]
    end = completions[-1]['at'] if completions else float('inf')
    starts = [e for e in events if e['event'] == 'onSlideShowBegin' and e['at'] <= end]
    if not starts:
        raise ValueError('No browser playback start was recorded')
    start = started_at if started_at is not None else starts[-1]['at']
    if not any(e['at'] == start for e in starts):
        raise ValueError('Requested browser playback start was not recorded')
    next_start = min((e['at'] for e in events if e['event'] == 'onSlideShowBegin' and e['at'] > start), default=float('inf'))
    stop = min((e['at'] for e in events if e['event'] == 'stopped' and e['at'] > start), default=float('inf'))
    window_end = min(end, next_start - 1, stop)
    complete = bool(completions) and end <= window_end
    run = [e for e in events if start <= e['at'] <= window_end]
    counts = Counter(e['page'] for e in run if e['event'] == 'audio-ended')
    requests = [e for e in run if e['event'] == 'animation-request']
    ended = [e for e in run if e['event'] == 'audio-ended']
    expected = [(p + 1, c + 1) for p, page in enumerate(sample['pages']) for c in range(len(page['cues']))]
    actual = [(e['page'], e['cue']) for e in requests]
    ended_pairs = [(e['page'], e['cue']) for e in ended]
    delays = sorted(int(m[1]) for e in run if e['event'] == 'audio-playing'
                    if (m := re.search(r'(\d+) ms', e['detail'])))
    pause_at = None
    paused_ms = 0
    for e in run:
        if e['event'] == 'paused':
            pause_at = e['at']
        elif e['event'] == 'resumed' and pause_at is not None:
            paused_ms += e['at'] - pause_at
            pause_at = None
    duration_ms = end - start if complete else None
    return {
        'complete': complete,
        'startedAt': start,
        'completedAt': end if complete else None,
        'wallSeconds': round(duration_ms / 1000, 3) if duration_ms is not None else None,
        'pausedSeconds': round(paused_ms / 1000, 3),
        'activeSeconds': round((duration_ms - paused_ms) / 1000, 3) if duration_ms is not None else None,
        'audioFileSeconds': round(sum(c.get('audioDurationSeconds', 0) for p in sample['pages'] for c in p['cues']), 3),
        'audioEndedByPage': [counts[p] for p in range(1, 6)],
        'expectedByPage': [len(p['cues']) for p in sample['pages']],
        'animationRequestsInExactOrder': actual == expected,
        'audioEndedInExactOrder': ended_pairs == expected,
        'animationRequestToAudioPlayingMs': {
            'count': len(delays),
            'median': delays[len(delays) // 2] if delays else None,
            'p95': delays[min(len(delays) - 1, int(len(delays) * .95))] if delays else None,
            'max': max(delays) if delays else None,
        },
        'errors': [e for e in run if e['event'] in ('error', 'command-error', 'bridge-error')],
        'sourceSha256': sample['sourceSha256'],
        'sampleSha256': sample['sampleSha256'],
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('log', type=Path)
    parser.add_argument('sample', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--started-at', type=int, help='Exact onSlideShowBegin timestamp for an earlier run')
    args = parser.parse_args()
    report = json.dumps(analyze(args.log, args.sample, args.started_at), ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(report + '\n', encoding='utf8')
    print(report)
