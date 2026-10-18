# Kokoro 本地语音测试

本地教师端通过已有的 Lemonade TTS 适配器调用 Kokoro。这里运行的是
Kokoro ONNX CPU 服务，提供兼容的 `/v1/audio/speech` 接口，未安装完整 Lemonade 桌面应用。

## 启动与试听

在项目根目录运行：

```powershell
.\start-teacher-kokoro-local.ps1
```

脚本将启动本地 TTS、写入本地教师配置，再启动教师端。已运行时复用当前服务。
首次使用需要 Python 3.10–3.13，下载依赖和约 354 MB 模型；本机已配置 Python 3.11。

- 试听页：<http://127.0.0.1:13305/>
- 教师端：<http://127.0.0.1:3200/course-space>
- 本地 TTS API：`http://127.0.0.1:13305/v1`

试听页可输入文字、切换 8 个中文音色、设置语速，并显示音频时长和生成耗时。
默认女声为小伊 `zf_xiaoyi`，男声样本为 `zm_yunxi`。
先听固定样本，再用自己的讲稿测试数字、多音字、中英混读、标点停顿。
下载 WAV 后也可用其他播放器核对。合成和音质是两项验证：程序确认有有效音频，
发音和自然度由试听确认。

教师设置里的名称是“Lemonade TTS（本地）”；已有课件音频不会自动替换。
在“模型与语音设置 → 语音合成 → Lemonade TTS（本地）”的音色下拉框中选择声音。
选择后用于试听和新提交的课件配音；任务提交时保存音色，后续更改设置不会影响该任务。
要测试新配音，请新生成课件，或使用课件编辑器的重新配音功能。

## 文件位置与资源

运行时全部位于本项目 `teacher_agent/.runtime/kokoro/`，不进入 Git：

- `venv/`：独立 Python 环境。
- `models/`：Kokoro v1.0 FP32 ONNX、音色库和带 SHA256 的清单。
- `cache/`、`tmp/`：下载缓存、分词缓存和临时文件。
- `samples/`：试听音频；`smoke.json`、`teacher-smoke.json`：实测记录。
- `stdout.log`、`stderr.log`：服务日志。
- `previous-local-tts.json`：切换前的 4 个 TTS 配置项备份，不备份 API Key。

服务仅监听 `127.0.0.1`，使用 CPU、4 个推理线程，同一时刻合成 1 段。
中文使用与 v1.0 配套的 Misaki 音素转换；英文单词单独转换为英文音素。
接口输出 24 kHz、16 位、单声道 WAV。此版本不提供 MP3 或声音克隆。

本地 `.env.local` 新增/调整：

```dotenv
TTS_LEMONADE_BASE_URL=http://127.0.0.1:13305/v1
TTS_LEMONADE_MODELS=kokoro-v1
TTS_LEMONADE_VOICE=zf_xiaoyi
TTS_QWEN_ENABLED=false
```

后台配音使用配置的中文默认音色；页面明确选择的音色优先。
PPT 转换保留已配置的托管 TTS，避免强制切回 Qwen。
这里只替换语音合成。DeepSeek 等生成课件内容的语言模型仍按原配置调用。

## 复测与恢复

服务启动后，在根目录运行真实音频检查：

```powershell
teacher_agent/.runtime/kokoro/venv/Scripts/python.exe teacher_agent/devtools/kokoro-local/smoke_test.py --root teacher_agent/.runtime/kokoro
teacher_agent/.runtime/kokoro/venv/Scripts/python.exe teacher_agent/devtools/kokoro-local/smoke_test.py --root teacher_agent/.runtime/kokoro --teacher
```

恢复切换前的本地 TTS 配置，不改其他环境变量：

```powershell
teacher_agent/.runtime/kokoro/venv/Scripts/python.exe teacher_agent/devtools/kokoro-local/configure_teacher.py --restore
```

重启教师端后，在语音设置中重新选择原提供方。单独前台启动/停止 TTS：

```powershell
.\start-kokoro-local.ps1
# 停止该前台进程：Ctrl+C
```

后台启动的服务可在任务管理器中按本项目 `venv/Scripts/python.exe` 的路径确认后结束。
关闭试听页面不停止服务。本地部署未修改云端配置。

模型与依赖来自公开官方项目：
[Kokoro ONNX](https://github.com/thewh1teagle/kokoro-onnx)、
[Misaki](https://github.com/hexgrad/misaki)、
[Kokoro 模型卡](https://huggingface.co/hexgrad/Kokoro-82M)。
