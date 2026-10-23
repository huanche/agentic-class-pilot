"""Validate both CPU models and reference registration without changing provider defaults."""
import base64
import io
import json
from pathlib import Path
import struct
import time
import urllib.request
import uuid
import wave


def request(path, payload=None):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request('http://127.0.0.1:13306' + path, data=data,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=180) as response:
        return response.read()


def synthesize(model, voice, text):
    start = time.monotonic()
    audio = request('/v1/audio/speech', {'model': model, 'voice': voice, 'input': text})
    with wave.open(io.BytesIO(audio)) as stream:
        seconds = stream.getnframes() / stream.getframerate()
        assert stream.getframerate() == 24000 and stream.getsampwidth() == 2
        samples = struct.unpack('<' + 'h' * stream.getnframes(), stream.readframes(stream.getnframes()))
        assert seconds > 1 and max(abs(x) for x in samples) > 100, 'Silent or truncated audio'
    return audio, {'model': model, 'seconds': round(seconds, 3),
                   'generationSeconds': round(time.monotonic() - start, 3), 'bytes': len(audio)}


if __name__ == '__main__':
    text = '同学们好，今天学习 C 语言，循环先判断条件，再执行循环体。'
    small, first = synthesize('hojo-tts-light-40m', 'hojo_zh_f_01', text)
    clone = 'hojo_clone_' + uuid.uuid4().hex
    registered = json.loads(request('/v1/audio/voices', {'voice_id': clone,
        'reference_audio': base64.b64encode(small).decode(), 'reference_text': text}))
    assert registered['voice_id'] == clone
    _, second = synthesize('hojo-tts-light-80m', clone, '现在学习循环的退出条件。')
    # Fixtures are not user voices. Clean only the exact ID created by this test.
    for suffix in ('.json', '.wav'):
        (Path('/runtime/references') / (clone + suffix)).unlink(missing_ok=True)
    print('VERIFY_HOJO_' + json.dumps({'40m': first, '80mClone': second}), flush=True)
