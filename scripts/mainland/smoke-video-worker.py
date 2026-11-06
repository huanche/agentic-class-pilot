#!/usr/bin/env python3
"""Record an animated, narrated fixture with the candidate worker image."""
import array
import json
import math
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid
import wave

KEY = 'isolated-video-release-test-key-' * 2
VERSION = 'a' * 64
CLIP = 'b' * 64
AUDIO = 'c' * 64 + '.wav'
ORIGIN = 'https://video-fixture.example'
ROOM = 'release_smoke'


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True, timeout=120).strip()


def run(image):
    name = 'agentic-video-smoke-' + uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        root.chmod(0o755)
        videos = root / 'videos'
        room = videos / ROOM
        for directory in ('versions', 'assets', 'jobs', 'clips', 'debug'):
            folder = room / directory
            folder.mkdir(parents=True, exist_ok=True)
            folder.chmod(0o777)
        (room / 'versions' / f'{VERSION}.json').write_text(json.dumps({
            'id': ROOM, 'version': VERSION, 'clips': [{
                'sceneId': 'scene_1', 'key': CLIP, 'audio': {'speech_1': {'file': AUDIO}},
            }],
        }))
        with wave.open(str(room / 'assets' / AUDIO), 'wb') as wav:
            wav.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
            wav.writeframes(array.array('h', (round(6000 * math.sin(n / 48000 * 440 * math.tau))
                                               for n in range(31200))).tobytes())
        (root / 'fixture.cjs').write_text(r"""
require('node:http').createServer((req, res) => {
  if (req.headers['x-classroom-render-grant'] !== 'smoke-grant') {
    res.writeHead(403).end(); return;
  }
  res.setHeader('content-type', 'text/html');
  res.end(`<!doctype html><style>body{background:#165f7b;color:white;font:60px sans-serif}</style>
    <h1>MP4 release fixture</h1><script>
    const wait = (ms) => new Promise(r => setTimeout(r, ms));
    window.classroomCapture = {
      async ready(id) {
        if (id !== 'scene_1') throw Error('Wrong page');
        await wait(100);
      },
      async run(durations) {
        if (durations.speech_1 < .5 || durations.speech_1 > .8) throw Error('Wrong audio');
        await wait(150);
        document.body.style.background = '#b33f6a';
        const speech = [{ actionId: 'speech_1', epoch: Date.now() }];
        await wait(900);
        return { speech, endEpoch: Date.now() };
      }
    };
    </script>`);
}).listen(9011, '127.0.0.1');
""")
        for source in (root / 'fixture.cjs', room / 'versions' / f'{VERSION}.json', room / 'assets' / AUDIO):
            source.chmod(0o644)

        def request(method, route, payload=None, authenticated=True):
            code = '''
const [method, route, body, key] = process.argv.slice(1);
const headers = { 'content-type': 'application/json' };
if (key) headers['x-video-worker-key'] = key;
fetch('http://127.0.0.1:9010' + route, {
  method, headers, ...(body ? { body } : {}), signal: AbortSignal.timeout(4000)
}).then(async r => console.log(JSON.stringify([r.status, await r.json()]))).catch(e => {
  console.error(e.name); process.exitCode = 1;
});
'''
            return json.loads(docker('exec', name, 'node', '-e', code, method, route,
                                     json.dumps(payload) if payload else '', KEY if authenticated else ''))

        try:
            docker('run', '--detach', '--name', name, '--network', 'none',
                   '--shm-size', '256m',
                   '--env', f'CLASSROOM_VIDEO_WORKER_KEY={KEY}',
                   '--env', f'VIDEO_PUBLIC_ORIGIN={ORIGIN}',
                   '--env', 'VIDEO_TEACHER_URL=http://127.0.0.1:9011',
                   '--env', 'VIDEO_CAPTURE_PROXY_TEACHER=true',
                   '--mount', f'type=bind,source={videos},target=/videos',
                   '--mount', f'type=bind,source={root / "fixture.cjs"},target=/fixture.cjs,readonly',
                   image)
            docker('exec', '-d', name, 'node', '/fixture.cjs')
            for _ in range(30):
                try:
                    if request('GET', '/health')[0] == 200:
                        break
                except subprocess.CalledProcessError:
                    time.sleep(1)
            else:
                raise RuntimeError('Worker never became healthy')
            assert request('POST', '/drain', authenticated=False)[0] == 403
            job = {'id': ROOM, 'version': VERSION, 'origin': ORIGIN, 'grant': 'smoke-grant'}
            accepted = request('POST', '/jobs', job)
            assert accepted[0] == 202, accepted
            assert request('POST', '/drain') == [200, {'draining': True}]
            assert request('POST', '/jobs', job)[0] == 503
            status_file = room / 'jobs' / f'{VERSION}.json'
            for _ in range(100):
                status = json.loads(status_file.read_text())
                if status['state'] == 'ready':
                    break
                if status['state'] == 'failed':
                    raise RuntimeError(status['error'])
                time.sleep(1)
            else:
                raise RuntimeError('The in-flight recording did not finish after draining')
            result = request('GET', '/health')[1]
            assert result['draining'] and not result['active'] and not result['queued']
            assert request('DELETE', '/drain') == [200, {'draining': False}]
            clip = f'/videos/{ROOM}/clips/{CLIP}.mp4'
            output = json.loads(docker('exec', name, 'ffprobe', '-v', 'error', '-show_streams',
                                       '-of', 'json', clip))
            assert {(s['codec_type'], s['codec_name']) for s in output['streams']} == {
                ('video', 'h264'), ('audio', 'aac')}
            meta = json.loads((room / 'clips' / f'{CLIP}.mp4.json').read_text())
            assert meta['frames'] >= 2 and 0 <= meta['speech'][0]['offset'] < meta['duration'] - .3
            # Check that the expected tone reached the output rather than merely an AAC stream.
            result = subprocess.run(['docker', 'exec', name, 'ffmpeg', '-i', clip, '-vn', '-af',
                                     'volumedetect', '-f', 'null', '-'], capture_output=True,
                                    text=True, check=True, timeout=15)
            level = re.search(r'max_volume: (-?\d+\.\d+) dB', result.stderr)
            assert level and float(level[1]) > -35
            print('MP4_SMOKE_OK: animated frames, audible AAC, queue drained without interrupting the clip')
        finally:
            subprocess.run(['docker', 'rm', '-f', name], capture_output=True, check=False, timeout=30)


if __name__ == '__main__':
    run(sys.argv[1])
