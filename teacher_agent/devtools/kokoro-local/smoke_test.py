"""Synthesize real local samples, check PCM, and exercise the teacher adapter."""

import argparse
import base64
import io
import json
from pathlib import Path
import urllib.error
import urllib.request
import wave

import numpy as np


def post(url, payload):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return response.read(), response.headers


def inspect_wav(data):
    with wave.open(io.BytesIO(data), "rb") as wav:
        assert wav.getnchannels() == 1 and wav.getsampwidth() == 2
        duration = wav.getnframes() / wav.getframerate()
        pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(float) / 32768
        rms = float(np.sqrt(np.mean(pcm * pcm)))
        assert duration > 1 and rms > 0.001, "Empty or silent audio"
        return {"durationSeconds": round(duration, 3), "sampleRate": wav.getframerate(),
                "rms": round(rms, 4), "peak": round(float(np.max(np.abs(pcm))), 4)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--teacher", action="store_true")
    args = parser.parse_args()
    samples = args.root / "samples"
    samples.mkdir(parents=True, exist_ok=True)
    results = []
    if args.teacher:
        data, _ = post("http://127.0.0.1:3200/api/generate/tts", {
            "text": "同学们好，这段声音通过本地教师端接口生成。现在我们学习变量，请观察左侧的示例。",
            "audioId": "tts_local_kokoro_smoke", "ttsProviderId": "lemonade-tts",
            "ttsModelId": "kokoro-v1", "ttsVoice": "zf_xiaoyi", "ttsSpeed": 1,
        })
        result = json.loads(data)
        assert result.get("success") is True
        audio = base64.b64decode(result["base64"])
        (samples / "teacher-api.wav").write_bytes(audio)
        results.append({"file": "teacher-api.wav", **inspect_wav(audio)})
    else:
        cases = [
            ("xiaoyi.wav", "zf_xiaoyi", "同学们好，我是小伊。这段声音由本地模型生成。今天我们学习变量和数据类型，请观察左侧的示例，再比较整数和字符串的区别。"),
            ("zh-female.wav", "zf_xiaobei", "同学们好，欢迎来到本地语音测试。今天我们学习变量和数据类型。请先观察左侧的示例，再比较整数、浮点数和字符串的区别。"),
            ("zh-male.wav", "zm_yunxi", "同学们好，欢迎来到本地语音测试。今天我们学习变量和数据类型。请先观察左侧的示例，再比较整数、浮点数和字符串的区别。"),
            ("python.wav", "zf_xiaobei", "在 Python 中，print 用来输出结果，input 用来读取输入。变量 age 等于18。中位数需要先排序：1、2、3、4、20，中间的数是3。"),
        ]
        for filename, voice, text in cases:
            audio, headers = post("http://127.0.0.1:13305/v1/audio/speech", {
                "model": "kokoro-v1", "input": text, "voice": voice,
                "speed": 1, "response_format": "wav",
            })
            (samples / filename).write_bytes(audio)
            result = {"file": filename, "voice": voice, **inspect_wav(audio),
                      "generationSeconds": float(headers["X-Generation-Seconds"])}
            result["realTimeFactor"] = round(result["generationSeconds"] / result["durationSeconds"], 3)
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
        for payload in ({"input": ""}, {"input": "你好", "voice": "missing"}, {"input": "你好", "speed": -1}):
            try:
                post("http://127.0.0.1:13305/v1/audio/speech", payload)
                raise AssertionError("Invalid input was accepted")
            except urllib.error.HTTPError as error:
                assert error.code == 400
    report = args.root / ("teacher-smoke.json" if args.teacher else "smoke.json")
    report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": True, "samples": len(results)}), flush=True)


if __name__ == "__main__":
    main()
