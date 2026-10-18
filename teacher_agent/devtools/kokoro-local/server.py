"""Loopback-only Kokoro CPU service compatible with the teacher's Lemonade adapter."""

import argparse
import io
import json
import math
import os
from pathlib import Path
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


VOICE_LABELS = {
    "zf_xiaobei": "小贝 · 中文女声",
    "zf_xiaoni": "小妮 · 中文女声",
    "zf_xiaoxiao": "晓晓 · 中文女声",
    "zf_xiaoyi": "小伊 · 中文女声",
    "zm_yunjian": "云健 · 中文男声",
    "zm_yunxi": "云希 · 中文男声",
    "zm_yunxia": "云夏 · 中文男声",
    "zm_yunyang": "云扬 · 中文男声",
}
DEFAULT_VOICE = "zf_xiaoyi"


class Engine:
    def __init__(self, root: Path, threads: int, model_dir: Path | None = None):
        import jieba
        import kokoro_onnx
        import onnxruntime as ort
        from misaki import zh

        # Keep Jieba's dictionary cache inside this checkout as well.
        jieba.dt.tmp_dir = str(root / "tmp")
        jieba.setLogLevel(30)
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        model_dir = model_dir or root / "models"
        session = ort.InferenceSession(
            str(model_dir / "kokoro-v1.0.onnx"),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self.model = kokoro_onnx.Kokoro.from_session(
            session, str(model_dir / "voices-v1.0.bin")
        )
        # v1.0 weights require the legacy IPA frontend, not the v1.1 vocabulary.
        self.zh = zh.ZHG2P()
        self.voices = sorted(self.model.get_voices())
        self.lock = threading.BoundedSemaphore(1)
        self.threads = threads

    def phonemize(self, text: str, voice: str) -> str:
        if not voice.startswith("z"):
            return self.model.tokenizer.phonemize(text, lang="en-us")
        # The v1.0 Chinese frontend preserves Latin text verbatim. Phonemize it
        # explicitly so words such as Python are spoken instead of dropped.
        parts = re.split(r"([A-Za-z]+(?:[ '\-]+[A-Za-z]+)*)", text)
        phonemes = []
        for index, part in enumerate(parts):
            if not part.strip():
                continue
            if index % 2:
                phonemes.append(self.model.tokenizer.phonemize(part, lang="en-us"))
            else:
                phonemes.append(self.zh(part)[0])
        return " ".join(phonemes)

    def synthesize(self, text: str, voice: str, speed: float):
        import soundfile as sf

        started = time.perf_counter()
        phonemes = self.phonemize(text, voice)
        if not self.model.tokenizer.tokenize(phonemes, limit=None):
            raise ValueError("文字没有可朗读的内容")
        samples, rate = self.model.create(phonemes, voice, speed, is_phonemes=True)
        buffer = io.BytesIO()
        sf.write(buffer, samples, rate, format="WAV", subtype="PCM_16")
        return buffer.getvalue(), len(samples) / rate, time.perf_counter() - started


def handler_for(engine: Engine, root: Path):
    class Handler(BaseHTTPRequestHandler):
        server_version = "LocalKokoro/1.0"

        def send(self, status, body, content_type="application/json; charset=utf-8", headers=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for name, value in (headers or {}).items():
                self.send_header(name, str(value))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def error(self, status, message):
            self.send(status, {"error": {"message": message}})

        def do_GET(self):
            route = urlsplit(self.path).path
            if route == "/":
                self.send(200, Path(__file__).with_name("listen.html").read_bytes(), "text/html; charset=utf-8")
            elif route == "/health":
                self.send(200, {"status": "ready", "engine": "kokoro-onnx", "model": "kokoro-v1",
                                "device": "cpu", "threads": engine.threads, "defaultVoice": DEFAULT_VOICE})
            elif route == "/v1/models":
                self.send(200, {"object": "list", "data": [{"id": "kokoro-v1", "object": "model", "owned_by": "local"}]})
            elif route == "/v1/voices":
                self.send(200, {"voices": [{"id": v, "name": VOICE_LABELS.get(v, v)} for v in engine.voices]})
            elif route in ("/samples/xiaoyi.wav", "/samples/zh-female.wav", "/samples/zh-male.wav", "/samples/python.wav", "/samples/teacher-api.wav"):
                sample = root / "samples" / route.rsplit("/", 1)[1]
                if sample.is_file():
                    self.send(200, sample.read_bytes(), "audio/wav")
                else:
                    self.error(404, "试听音频尚未生成")
            else:
                self.error(404, "Not found")

        def do_POST(self):
            if urlsplit(self.path).path != "/v1/audio/speech":
                self.error(404, "Not found")
                return
            # A local web page can call this endpoint; reject browser requests
            # originating on unrelated websites. Node's teacher requests omit Origin.
            origin = self.headers.get("Origin")
            if origin and urlsplit(origin).hostname not in ("127.0.0.1", "localhost", "::1"):
                self.error(403, "Only local callers are allowed")
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size < 1 or size > 64 * 1024:
                    raise ValueError("请求体必须在 1 到 65536 字节之间")
                request = json.loads(self.rfile.read(size))
                if not isinstance(request, dict):
                    raise ValueError("请求必须是 JSON 对象")
                text = request.get("input", "")
                if not isinstance(text, str) or not text.strip() or len(text) > 5000:
                    raise ValueError("请输入 1 到 5000 字的朗读内容")
                voice = request.get("voice") or DEFAULT_VOICE
                if voice not in engine.voices:
                    raise ValueError("音色不存在，请从音色列表选择")
                speed = float(request.get("speed", 1))
                if not math.isfinite(speed) or not 0.5 <= speed <= 2:
                    raise ValueError("语速范围为 0.5 到 2")
                if request.get("model", "kokoro-v1") not in ("kokoro-v1", "kokoro"):
                    raise ValueError("本地模型为 kokoro-v1")
                if request.get("response_format", "wav") != "wav":
                    raise ValueError("本地服务目前输出 WAV 格式")
            except (ValueError, TypeError, KeyError):
                self.error(400, "请求参数有误，请检查文字、音色、语速和 WAV 格式")
                return
            # Bound the wait while allowing short requests from teacher TTS workers.
            if not engine.lock.acquire(timeout=100):
                self.error(429, "合成繁忙，请稍后重试")
                return
            try:
                audio, duration, seconds = engine.synthesize(text.strip(), voice, speed)
                self.send(200, audio, "audio/wav", {
                    "X-Audio-Duration": f"{duration:.3f}",
                    "X-Generation-Seconds": f"{seconds:.3f}",
                    "X-Voice": voice,
                })
                print(json.dumps({"event": "speech", "voice": voice, "characters": len(text),
                                  "audioSeconds": round(duration, 3), "generationSeconds": round(seconds, 3)}), flush=True)
            except ValueError as error:
                self.error(400, str(error))
            except Exception as error:
                print(json.dumps({"event": "synthesis_error", "type": type(error).__name__}), flush=True)
                self.error(500, "本地合成失败，请查看项目内的 Kokoro 日志")
            finally:
                engine.lock.release()

        def log_message(self, format, *args):
            # Do not log the text or any caller credentials.
            print(json.dumps({"event": "http", "method": self.command,
                              "path": urlsplit(self.path).path, "status": args[1] if len(args) > 1 else ""}), flush=True)

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--host", choices=("127.0.0.1", "0.0.0.0"), default="127.0.0.1")
    parser.add_argument("--port", type=int, default=13305)
    parser.add_argument("--threads", type=int, default=4, choices=range(1, 17))
    args = parser.parse_args()
    root = args.root.resolve()
    for folder in ("tmp", "samples", "cache/huggingface"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = str(root / "tmp")
    os.environ["TMP"] = str(root / "tmp")
    os.environ["HF_HOME"] = str(root / "cache" / "huggingface")
    os.environ["OMP_NUM_THREADS"] = str(args.threads)
    engine = Engine(root, args.threads, args.model_dir)
    server = ThreadingHTTPServer((args.host, args.port), handler_for(engine, root))
    server.daemon_threads = True
    print(json.dumps({"event": "ready", "url": f"http://127.0.0.1:{args.port}", "device": "cpu"}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
