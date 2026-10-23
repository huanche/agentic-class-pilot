"""Loopback-only Hojo ONNX service; models stay warm, requests keep audio/action ordering."""
import argparse
import base64
import gc
import hmac
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import numpy as np
import soundfile as sf

MODEL_IDS = {'hojo-tts-light-40m': '40m', 'hojo-tts-light-80m': '80m'}
CLONE_RE = re.compile(r'^hojo_clone_[a-f0-9]{32}$')
SAMPLE_RATE = 24000
REFERENCE_TEXT = '现在的外卖确实坑多，要不咱换家稍微贵点的？可能品质好点。'


def split_text(text):
    """Bound each autoregressive segment without cutting words or dropping punctuation."""
    chunks, current = [], ''
    for unit in re.findall(r'.+?(?:[。！？!?；;\n]|$)', text, re.S):
        limit = 110 if re.search(r'[\u4e00-\u9fff]', unit) else 300
        pieces = re.findall(r'\S+\s*', unit) if not re.search(r'[\u4e00-\u9fff]', unit) else list(unit)
        for piece in pieces:
            if len(current) + len(piece) > limit and current:
                chunks.append(current.strip())
                current = ''
            current += piece
        if len(current) >= limit // 2:
            chunks.append(current.strip())
            current = ''
    if current.strip():
        chunks.append(current.strip())
    return chunks


class Engine:
    def __init__(self, root, threads):
        self.root, self.threads = root, threads
        self.lock = threading.Lock()
        self.model = self.size = None
        self.references = root / 'references'
        self.references.mkdir(exist_ok=True)

    def load(self, size):
        if self.size == size:
            return self.model
        self.model = self.size = None
        gc.collect()
        source = self.root / 'upstream' / size / 'onnx_model.py'
        if not source.exists() or not (self.root / 'models' / size).exists():
            raise ValueError(f'{size} 模型尚未安装，请先运行模型下载脚本')
        spec = importlib.util.spec_from_file_location(f'hojo_runtime_{size}', source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        model = module.HojoTTSLightOnnx(self.root / 'models' / size,
                                       provider='cpu', num_threads=self.threads)
        self.model, self.size = model, size
        return model

    def voice_exists(self, voice):
        return bool(CLONE_RE.fullmatch(voice) and (self.references / f'{voice}.json').exists())

    def register(self, body):
        voice = body.get('voice_id', '')
        if not isinstance(voice, str) or not CLONE_RE.fullmatch(voice):
            raise ValueError('克隆音色 ID 无效')
        if self.voice_exists(voice):
            return voice
        audio = base64.b64decode(body.get('reference_audio', ''), validate=True)
        if len(audio) > 10 * 1024 * 1024:
            raise ValueError('参考音频不得超过 10 MB')
        wav, rate = sf.read(io.BytesIO(audio), dtype='float32', always_2d=True)
        seconds = len(wav) / rate
        if not 1 <= seconds <= 30 or not np.isfinite(wav).all() or np.max(np.abs(wav)) < 0.001:
            raise ValueError('请上传 1～30 秒、可正常播放的非静音参考音频')
        text = body.get('reference_text', '')
        if not isinstance(text, str) or len(text) > 2000:
            raise ValueError('参考音频文字过长')
        # Immutable random voice IDs keep audio-cache identities stable.
        sf.write(self.references / f'{voice}.wav', wav.mean(axis=1), rate, subtype='PCM_16')
        (self.references / f'{voice}.json').write_text(json.dumps({'text': text}, ensure_ascii=False), encoding='utf-8')
        return voice

    def synthesize(self, body):
        text = body.get('input', '')
        model_id = body.get('model', 'hojo-tts-light-40m')
        if model_id not in MODEL_IDS:
            raise ValueError('不支持的 Hojo 模型')
        if not isinstance(text, str) or not text.strip() or len(text) > 5000:
            raise ValueError('讲稿不能为空且不得超过 5000 字')
        if body.get('response_format', 'wav') != 'wav' or body.get('speed', 1) != 1:
            raise ValueError('Hojo 当前以原速输出 WAV；播放倍速由课件播放器控制')
        size = MODEL_IDS[model_id]
        voice = body.get('voice') or ('hojo_zh_f_01' if size == '40m' else 'hojo_80m_zh1')
        reference = None
        if size == '80m':
            if voice == 'hojo_80m_zh1':
                reference = (self.root / 'upstream' / size / 'assets' / 'zh1.wav', REFERENCE_TEXT)
            elif isinstance(voice, str) and self.voice_exists(voice):
                data = json.loads((self.references / f'{voice}.json').read_text(encoding='utf-8'))
                reference = (self.references / f'{voice}.wav', data['text'])
            else:
                raise ValueError('80M 需要选择官方示例音色或已上传的克隆音色')
        started = time.perf_counter()
        with self.lock:
            model = self.load(size)
            if size == '40m' and voice not in model.available_voices:
                raise ValueError('40M 固定音色无效；克隆音色请使用 80M')
            segments = []
            for part in split_text(text.strip()):
                params = {'voice': voice} if size == '40m' else {'prompt_speech': str(reference[0]), 'prompt_text': reference[1]}
                wav = model.generate(part, **params)
                if not len(wav) or not np.isfinite(wav).all() or np.max(np.abs(wav)) < 0.0001:
                    raise RuntimeError('Hojo 合成音频为空或静音')
                segments.append(np.asarray(wav, dtype=np.float32).reshape(-1))
            if not segments:
                raise ValueError('讲稿没有可合成的文字')
            wav = np.concatenate(segments)
            output = io.BytesIO()
            sf.write(output, wav, SAMPLE_RATE, format='WAV', subtype='PCM_16')
        elapsed = time.perf_counter() - started
        seconds = len(wav) / SAMPLE_RATE
        print(json.dumps({'model': model_id, 'voice': voice, 'characters': len(text),
                          'elapsedSeconds': round(elapsed, 3), 'audioSeconds': round(seconds, 3),
                          'rtf': round(elapsed / seconds, 3)}), flush=True)
        return output.getvalue(), elapsed, seconds


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send(self, status, body, content_type='application/json', headers=None):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        for key, value in (headers or {}).items():
            self.send_header(key, str(value))
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        key = os.environ.get('HOJO_API_KEY', '')
        return not key or hmac.compare_digest(self.headers.get('Authorization', ''), f'Bearer {key}')

    def do_GET(self):
        if not self.authorized():
            return self.send(401, {'error': 'Unauthorized'})
        path = urlsplit(self.path).path
        if path == '/health':
            return self.send(200, {'status': 'ok', 'loadedModel': self.server.engine.size})
        if path == '/v1/models':
            return self.send(200, {'data': [{'id': key} for key, size in MODEL_IDS.items() if (self.server.engine.root / 'models' / size).exists()]})
        if path.startswith('/v1/audio/voices/'):
            voice = path.rsplit('/', 1)[-1]
            return self.send(200 if self.server.engine.voice_exists(voice) else 404, {'voice_id': voice})
        return self.send(404, {'error': 'Not found'})

    def do_POST(self):
        if not self.authorized():
            return self.send(401, {'error': 'Unauthorized'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 14 * 1024 * 1024:
                return self.send(413, {'error': '请求过大或缺少 Content-Length'})
            self.connection.settimeout(180)
            body = json.loads(self.rfile.read(length))
            path = urlsplit(self.path).path
            if path == '/v1/audio/voices':
                return self.send(200, {'voice_id': self.server.engine.register(body)})
            if path == '/v1/audio/speech':
                wav, elapsed, seconds = self.server.engine.synthesize(body)
                return self.send(200, wav, 'audio/wav', {'X-Synthesis-Seconds': elapsed, 'X-Audio-Seconds': seconds})
            return self.send(404, {'error': 'Not found'})
        except (ValueError, KeyError, TypeError) as error:
            return self.send(400, {'error': str(error)})
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as error:
            print(json.dumps({'error': type(error).__name__, 'message': str(error)[:300]}), flush=True)
            return self.send(500, {'error': 'Hojo 合成失败，请查看本地语音服务日志'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--port', type=int, default=13306)
    parser.add_argument('--threads', type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.threads <= 32:
        parser.error('threads must be 1..32')
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.engine = Engine(args.root.resolve(), args.threads)
    print(json.dumps({'listening': f'http://127.0.0.1:{args.port}', 'threads': args.threads}), flush=True)
    server.serve_forever()
