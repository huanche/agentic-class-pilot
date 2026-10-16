# 讲解与聚焦的生成校验

本次修改针对新生成的幻灯片，不会重写已有课程 JSON。旧课件可以作为回归输入，已有的跨主题音频仍须重新生成讲解和配音。

## 流程

1. 五个应用生成入口共用 `lib/server/aligned-scene-actions.ts`。
2. 提示词要求按“可见目标元素 + 对应讲稿”生成单元，并提供完整文字、表格、图表数据和形状文字。
3. 后处理保留原始单元边界；旧的讲稿长度限制只在原来的段落内裁剪，不能把句子移动到其他目标下。
4. 先检查元素 ID、可见性、重复动作 ID、孤立聚焦和每段目标数量。随后另行调用模型逐段检查内容是否对应、是否跨视觉主题。审核必须覆盖全部最终讲稿并保留准确的目标 ID，缺段或无效响应不能算通过。
5. 不通过时反馈具体问题并重新生成一次。仍失败则返回 422 `FOCUS_SPEECH_ALIGNMENT_FAILED`，不配音、不发布，也不能自动降级成已完成页面。编辑工具保留原课件。
6. 校验通过后逐段配音，清除生成结果携带的旧音频引用。因配音提供商长度限制而拆分的片段继承同一聚焦；reveal 不重复执行。
7. 播放器执行已经确定的目标，不按关键词重新猜测。聚焦随真实音频结束而清除，暂停时保留。独立实时动作仍使用原来的自动清除计时。

语义审核仍是模型判断；本机制提供逐次检查和失败阻断，不是数学意义上的语义正确性保证。没有足够图像证据时要求拒绝猜测。互动 HTML 继续使用原有 widget 动作协议，不经过幻灯片目标校验。

## 本地测试

从 `teacher_agent` 运行：

```powershell
node node_modules/vitest/vitest.mjs run tests/generation/aligned-scene-actions.test.ts tests/server/scene-actions-alignment-route.test.ts tests/audio/tts-utils.test.ts tests/import/ppt-narration.test.ts tests/playback/focus-speech-sync.test.ts tests/hooks/use-scene-generator-retry.test.ts --maxWorkers=1
node node_modules/typescript/bin/tsc --noEmit --incremental false
```

## 真实模型与配音测试

`devtools/narration-alignment/smoke.ts` 先要求真实审核模型拒绝一个已知的跨主题错误，再为 Python 两类报错、编辑器比较表和赋值结论揭示生成全新测试页面。测试 ID 每次重新分配。设置 `FOCUS_SMOKE_TTS=1` 时，对通过检查的讲稿生成真实音频。

`build-smoke.mjs <output.mjs>` 将当前代码与包内提示词打包为单独的 Node 程序。`FOCUS_SMOKE_CHECK_ONLY=1` 仅验证导入和提示词资源，不调用模型。

`.github/workflows/narration-alignment-smoke.yml` 在测试分支构建此程序，通过单独的 Node 进程读取服务器现有模型配置，输出只写入 `/tmp/agentic-focus-smoke-<run-id>/results`。它不替换服务容器，也不保存或修改课程。测试的 JSON 和音频作为七天有效的 Actions artifact 保留。

正常生成每页新增一次语义审核。内容修正最多一次；取消及提供商错误按原来的调用路径处理，不当作语义修正反复调用。
