"""Prepare the fixed test's Kokoro clips; no production classroom is written."""
from pathlib import Path
import argparse
import array
import hashlib
import json
import math
import time
import urllib.request
import wave


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('data', type=Path)
    parser.add_argument('--endpoint', required=True)
    args = parser.parse_args()
    sample = json.loads((args.data / 'sample.json').read_text(encoding='utf8'))
    out = args.data / 'audio'
    out.mkdir(exist_ok=True)
    started = time.monotonic()
    report = []
    for p, page in enumerate(sample['pages']):
        for cue in page['cues']:
            target = out / cue['audio']
            speech_started = time.monotonic()
            reused = target.exists()
            if not reused:
                req = urllib.request.Request(
                    args.endpoint.rstrip('/') + '/audio/speech',
                    data=json.dumps({
                        'model': 'kokoro-v1', 'voice': 'zf_xiaoyi',
                        'input': cue['text'], 'response_format': 'wav', 'speed': 1,
                    }).encode('utf8'),
                    headers={'Content-Type': 'application/json'}, method='POST',
                )
                with urllib.request.urlopen(req, timeout=90) as response:
                    data = response.read(10_000_001)
                if len(data) > 10_000_000:
                    raise ValueError('Audio clip too large')
                temp = target.with_suffix('.tmp')
                temp.write_bytes(data)
                temp.replace(target)
            with wave.open(str(target), 'rb') as audio:
                duration = audio.getnframes() / audio.getframerate()
                if audio.getsampwidth() != 2:
                    raise ValueError('Expected PCM16 audio')
                samples = array.array('h', audio.readframes(audio.getnframes()))
            rms = math.sqrt(sum(x*x for x in samples[::16]) / max(1, len(samples[::16]))) / 32768
            if duration < .25 or rms < .0001:
                raise ValueError('Empty or silent narration')
            cue['audioDurationSeconds'] = round(duration, 4)
            report.append({
                'file': cue['audio'], 'durationSeconds': round(duration, 3),
                'synthesisSeconds': round(time.monotonic()-speech_started, 3),
                'rms': round(rms, 5), 'bytes': target.stat().st_size,
                'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'reused': reused,
            })
        print(json.dumps({'page': p+1, 'clipsComplete': len(report)}, ensure_ascii=False), flush=True)
    result = {
        'provider': 'Kokoro', 'voice': 'zf_xiaoyi', 'speed': 1,
        'clips': report, 'wallSeconds': round(time.monotonic()-started, 3),
        'playbackSeconds': round(sum(x['durationSeconds'] for x in report), 3),
    }
    (args.data / 'sample.json').write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding='utf8')
    (args.data / 'audio-report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k != 'clips'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
