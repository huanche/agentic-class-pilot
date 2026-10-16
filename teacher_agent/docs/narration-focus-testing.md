# 讲解与聚焦的生成校验

本次修改针对新生成的幻灯片，不会重写已有课程 JSON。旧课件可以作为回归输入，已有的跨主题音频仍须重新生成讲解和配音。

## 流程

1. 五个应用生成入口共用 `lib/server/aligned-scene-actions.ts`。
2. 模型直接输出教学片段计划，每段同时包含 `targetId`、`speech` 和用途。`lib/generation/teaching-plan.ts` 严格检查后，固定转换为已有播放器的 `spotlight/laser → speech` 动作；模型不再分别生成两个松散动作。主体讲解必须有目标，同一目标多段讲解会逐段生成聚焦。提供完整文字、表格、图表数据和形状文字、课程上下文、语言和时长要求。
3. 后处理保留原始单元边界；旧的讲稿长度限制只在原来的段落内裁剪，不能把句子移动到其他目标下。
4. 先检查元素 ID、可见性、重复动作 ID、孤立聚焦和每段目标数量。随后另行调用模型逐段检查内容是否对应、是否跨视觉主题。审核必须覆盖全部最终讲稿并保留准确的目标 ID，缺段或无效响应不能算通过。
5. 不通过时反馈实际候选与具体问题并重新生成一次。仍失败则返回 422 `FOCUS_SPEECH_ALIGNMENT_FAILED`，不配音、不发布，也不能自动降级成已完成页面。缺少实际页面元素、未知目标和旧的松散动作格式都不能绕过检查；编辑工具保留原课件。
6. 校验通过后逐段配音，清除生成结果携带的旧音频引用。因配音提供商长度限制而拆分的片段继承同一聚焦；reveal 不重复执行。
7. 播放器执行已经确定的目标，不按关键词重新猜测。聚焦随真实音频结束而清除，暂停时保留。独立实时动作仍使用原来的自动清除计时。
8. Qwen 配音接收课程语种：已知中文课程的纯汉字/数字片段使用 `Chinese`，避免短句被自动判断成日语；中英代码混合片段保留 `Auto`。服务器批量生成、时长校正、重新配音和浏览器配音入口均传递语种。没有语种上下文时保持原有自动识别。
9. 已结束的音频不会被当作暂停音频恢复，避免在结论 reveal 间隙暂停后重播前一句。

片段示例：

```json
{"segments":[{"kind":"narration","purpose":"explanation","targetId":"conclusion","speech":"因此得到这个结论。","revealBefore":true}]}
```

该段固定编译为 `reveal → spotlight → speech`。没有 reveal 的内容默认显示。视频和末尾讨论使用独立的受限片段，保留原来的同步播放与讨论协议。

语义审核仍是模型判断；本机制提供逐次检查和失败阻断，不是数学意义上的语义正确性保证。没有足够图像证据时要求拒绝猜测。互动 HTML 继续使用原有 widget 动作协议，不经过幻灯片目标校验。

Qwen 语种设置依据：[非实时 Qwen-TTS API](https://help.aliyun.com/zh/model-studio/qwen-tts-api)。实测中相同的“中位数先排序：1、2、3、4、20”文本在 Auto 模式出现日语发音；明确中文后重新合成并回译为正确中文。

## 本地测试

从 `teacher_agent` 运行：

```powershell
node node_modules/vitest/vitest.mjs run tests/generation/teaching-plan.test.ts tests/generation/aligned-scene-actions.test.ts tests/server/scene-actions-alignment-route.test.ts tests/audio/tts-utils.test.ts tests/import/ppt-narration.test.ts tests/playback/focus-speech-sync.test.ts tests/hooks/use-scene-generator-retry.test.ts --maxWorkers=1
node node_modules/typescript/bin/tsc --noEmit --incremental false
```

音频边界与语种回归：

```powershell
node node_modules/vitest/vitest.mjs run tests/audio/audio-player-ended.test.ts tests/audio/qwen-language.test.ts tests/audio/agent-voice.test.ts tests/server/classroom-tts-language.test.ts tests/server/classroom-narration-language-route.test.ts --maxWorkers=1
```

## 真实模型与配音测试

`devtools/narration-alignment/smoke.ts` 先要求真实审核模型拒绝一个已知的跨主题错误，再连续运行两轮、每轮五页：Python 两类报错、编辑器比较表、赋值结论揭示，以及平均数/中位数、for/while。后两页连页面内容也由模型重新生成。测试 ID 每次重新分配，不编辑现有课程。设置 `FOCUS_SMOKE_TTS=1` 时，对通过检查的讲稿生成真实音频。失败候选和审核报告保存在合成测试 artifact 中，测试不会把拒绝的页面计作通过。

`build-smoke.mjs <output.mjs>` 将当前代码与包内提示词打包为单独的 Node 程序。`FOCUS_SMOKE_CHECK_ONLY=1` 仅验证导入和提示词资源，不调用模型。

`.github/workflows/narration-alignment-smoke.yml` 由人工启动，可通过 `case_start/case_end` 补测指定样本，避免每次修改测试工具都自动消耗模型额度。它在测试分支构建此程序，通过单独的 Node 进程读取服务器现有模型配置，输出只写入 `/tmp/agentic-focus-smoke-<run-id>/results`。它不替换服务容器，也不保存或修改课程。测试的 JSON 和音频作为七天有效的 Actions artifact 保留。页面内容生成沿用正式流程的空结果重试机制，测试限制为一次重试；失败仍如实记录。

正常生成每页新增一次语义审核。内容修正最多一次；取消及提供商错误按原来的调用路径处理，不当作语义修正反复调用。

## 2026-10-16 验证记录

- 使用真实 DeepSeek 生成并审核五类新样本，全部通过后由 Qwen 生成 18 段音频。平均数/中位数、for/while 两页的页面内容也由模型重新生成；不修改现有 Python 课程。
- 逐段核对原始 `targetId + speech` 与编译结果，18 段绑定均保持不变。离线回译核对全部音频，并对英文术语片段另用 Qwen ASR 复核；回译存在同音字和英文拼写误差，不能据此声称发音逐字完美。
- 本地页面使用项目的真实渲染器、动作引擎和音频播放器，连续播放五页约 119.68 秒。18 次语音开始对应 18 次真实音频结束，播放中 1,247 次采样未发现目标错位。
- 实际浏览器在结论 reveal 期间暂停后继续，三段音频各播放一次，结论聚焦正确，未重播已结束的上一段。该问题和 Qwen 语种问题均有修复前失败、修复后通过的回归测试。
- 音频相关最新 21 项测试通过；TypeScript 无错误，修改文件 ESLint 无错误，保留一条原有未使用变量警告。更广回归 4,977 项通过、61 项跳过，排除了全量运行中十个未修改的已知失败文件；全量测试不是全部通过。
- 真实配音测试曾出现提供商请求超时，使用限定超时的本地测试传输单独补测后通过。超时尝试不计为成功；没有修改正式请求的超时或重试策略。五页样本通过不等于模型对任意输入都绝对正确，正式生成依靠逐段审核和失败阻断控制错误。

## 中断恢复时的模型选择

课程工作区生成使用服务器模型策略。原先该策略只保存在标签页的 `sessionStorage.generationParams`，重新打开标签页后会退回浏览器当前选中的模型。真实 Python 课件日志显示首屏使用 Flash，恢复第二页时改用了 Pro；第二页仍在生成、配音和最多两次时长校正，并未停止，但等待明显变长。

现在将 `generationModelPolicy` 随 Stage 保存。恢复时优先保留已存策略，其次使用原标签页参数。旧课件从课程工作区打开时可恢复服务器策略，并写回 Stage；独立的快速生成保留浏览器模型，已明确选择的浏览器策略也保留。此字段不保存 API Key 或指定某个具体模型名，服务器配置仍决定实际模型。

`tests/classroom/generation-model-resume.test.ts` 挂载实际课堂页面、模拟丢失会话和保留已有场景，验证恢复参数；两个用例在旧代码下以 `false !== true` 失败，修复后通过。
