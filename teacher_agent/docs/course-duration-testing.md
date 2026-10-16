# 课件播放时长与本地测试

教师可在生成入口填写正整数分钟，留空默认 **28 分钟**。此设置控制新课件的自动讲解与演示，排除学生自主答题、PBL、自由讨论、教师暂停和网络等待。旧课件不自动修改。

## 实现流程

1. 首页、PPT 转换及课程工作区写入结构化 `requirements.targetDurationMinutes`。
2. 大纲生成提示词明确目标、时长范围与页面深度。教师审核后，业务代码按模型给出的相对权重重新分配自动页面预算，合计严格等于目标秒数。
3. 页面内容模型收到本页预算，按目标增加有依据的案例、步骤、对比或演示状态等可见内容，而不是只增加旁白。AI 增强模式可规划更多页面；高保真模式仍保留原始画布与页数，通过讲解丰富内容。随后动作生成收到预算和讲稿长度参考，保留 reveal。使用时长预算时，不再把完整讲稿统一截为普通页 220 字、公式页 520 字。
4. 配音后读取 WAV/MP3 实际时长，加上已知的 reveal / widget 同步动作耗时。聚焦、激光笔不阻塞讲解。页面短过渡未包含在测量中；实测以正常播放速度为准。
5. 对完整可测且偏离本页目标超过 5% 的页面，按已选讲稿的字数/词数与实际配音时长计算本轮长度参考，替代首轮固定语速估计。最多重新生成讲稿和配音两次，保留最接近目标的可播放版本，清理弃用音频。不会用静音补足、强制截断语音或极端语速凑时长。
6. 全部自动页面配音完成后再汇总整课。整课超差时，优先对同方向偏差最大的页面重新生成讲稿和配音，最多额外两轮；只有整课总偏差缩小才采用候选版本。已达标或尚未完成测量时不再调用模型。浏览器不改写当前正在查看或编辑的页面，避免打断播放。整课轮次写入课件，刷新不会重置上限。
7. 页面显示目标、实测与达标状态。已生成且尚未耗尽整课轮次的超差课程可点击“校正整课时长”。校正期间暂停导出；只重写选中页的讲解动作与配音，画布、原课件预算及其他页面保留。服务失败或候选更差时保留可播放版本。未生成完、缺配音、音频容器不可测量，或含尚未测量的视频/白板动作时，显示尚未完成实测。达到重试上限仍偏离时，保留“偏短 / 偏长”。编辑讲稿后，旧测量失效；导入导出保留时长信息。

主要实现：`lib/generation/course-duration.ts`、`lib/generation/course-duration-calibration.ts`、`lib/hooks/use-scene-generator.ts`、`lib/server/classroom-generation.ts`，以及生成入口与展示组件。新生成课程的自动翻页不再按目标时间空等；既有课件仍沿用原播放规则。

## 无 API Key 的离线测试

在 `teacher_agent` 目录运行：

```powershell
node devtools/course-duration/preview.mjs
```

打开 <http://127.0.0.1:3214>。这里使用真实的输入组件、预算与音频测量函数，可验证留空、20 分钟、非法输入和预算合计。它是独立的离线测试页，不是完整教师工作区，不会调用模型或 TTS。

如果本地 `outputs/playback-diagnostics` 存在 `course-1.original.json` / `course-2.original.json` 及对应 `course-1-assets/audio` / `course-2-assets/audio`，会重新读取原始 WAV/MP3，展示原始音频时长及自动页面播放时长。可用 `COURSE_DURATION_FIXTURES` 指定其他目录。原始 JSON 和音频只读，不在 Git 提交范围。

自动化检查：

```powershell
pnpm exec vitest run tests/generation/course-duration.test.ts tests/server/classroom-generation-retry.test.ts tests/export/export-classroom-conversion.test.ts tests/playback --maxWorkers=1 --testTimeout=15000
pnpm exec tsc --noEmit --incremental false
```

## 真实生成测试

工程有模型与 TTS 的接入代码，真实密钥由教师端设置、部署环境或平台配置提供；仓库不需要包含密钥。配置入口及环境变量参见 `.env.example` 和 `lib/server/provider-config.ts`。

配置可用服务后运行 `pnpm dev`，生成两门新课：一门时长留空，一门输入 20。检查大纲预算总和分别为 1680 / 1200 秒，生成结束后检查“目标 / 实测 / 达标状态”。缺少真实服务时，离线检查不能证明实际新课件已达到 20 或 28 分钟。

本功能保留 reveal；不修复网络引起的音频停顿或音画同步问题。仅修改本地代码不会改变已部署网站，部署须另行执行。
