# ONLYOFFICE 原稿放映试验

这是独立的五页云端试验，入口 `/onlyoffice-test/`，没有改动生产课件的渲染器或生成任务。

## 样本与边界

- 使用教师提供的 `lec 9.PPT [修复的].pptx`，原文件 SHA256 为 `c1c0a615c6fb0034370b087c49222f3cfa1ec15c63ca9a506f270e94c718d2dc`。
- 提取原稿第 5—9 页，共五页、50 组点击动画。所选页面及其动画 XML 保持原字节；仅调整演示文稿页清单、关系和可达的包内容。
- `prepare-sample.py` 提取原稿并生成固定测试讲稿。讲稿是针对这些动画组编写的测试内容，不调用模型、不覆盖已有课程。
- `synthesize.py` 调用已有 Kokoro 服务，逐段生成 WAV 并检查有效 PCM、时长和非静音。默认音色 `zf_xiaoyi`、速度 1。
- 本试验只验证原生渲染、原生动画和外部配音的衔接，不代表任意 PPT 动画、字体或媒体均已兼容。

## 播放控制

页面使用 ONLYOFFICE 的只读 Presentation Editor 和后台插件。命令仅允许开始、结束、暂停、继续、下一步及固定五页内跳转。

`GoToSlideInSlideShow` 接收从 1 开始的页码，而 `onSlideShowSlideChanged` 返回从 0 开始的页索引。每次启动都明确跳到目标页，并等待换页过渡完成后才开始对象动画，避免第一条指令被换页过渡消耗。

每组动画对应一段配音；下一组等待当前音频的真实 `ended` 事件及原稿动画组的最小时长。暂停时间不计入动画经过时间。浏览器最多预取接下来的三段音频，减少片段之间的网络等待。测试记录包含原生页事件、动画请求、音频开始/结束、暂停及错误。

## 云端部署

官方 ONLYOFFICE DocumentServer 10.0.0 Build 169 固定镜像摘要：

```
sha256:ca17889f10b11141cc6441836aebdd2835cf3e1b49681b2fd6e155c94b7850b3
```

云端私有路径：

- `/opt/agentic-onlyoffice-lab/app`：此目录的代码。
- `/opt/agentic-onlyoffice-lab/data`：固定 PPTX、sample.json、audio/ 与合成报告。
- `/var/lib/agentic-onlyoffice-lab`：独立 JWT、平台授权配置、备份、测试日志；不进入仓库。

`cloud-start.sh` 启动独立的 `agentic-onlyoffice-lab` 与 `agentic-onlyoffice-docs` 容器，资源有上限，不自动重启，不替换生产教师应用。Docs 使用 internal Docker 网络，由现有 Caddy 转发两个测试前缀。网关上游使用容器的私有地址，运行时从 Docker 查询，不假设固定 IP。

在上述私有配置和样本准备完成后，由 root 执行：

```bash
bash /opt/agentic-onlyoffice-lab/app/cloud-start.sh
LAB_GATEWAY_RELOAD_MODE=restart bash /opt/agentic-onlyoffice-lab/app/cloud-gateway.sh enable
```

当前 Caddy 2.10 的管理接口关闭且不实现 SIGUSR1 热加载，脚本验证配置、获取已有部署锁、确认生成任务空闲后才重启网关，并检查教师服务与试验 JSON 健康状态。不能用 HTTP 200 单独判断测试入口已生效，生产 SPA 的回退也可能返回 200。

认证沿用平台 `agentedu_session`，限定为样本所属教师。自动测试可使用短期、只读、仅限本样本的能力令牌。原文件地址单独签名并限时，插件消息校验来源、窗口和会话随机数；不接受任意编辑器方法或任意文件路径。预览令牌、JWT、私钥和业务资料均不得提交。

## 回退

```bash
sudo bash /opt/agentic-onlyoffice-lab/app/cloud-stop.sh
```

这会只移除有标记的试验网关块、检查正式入口，然后停止带指定试验标签的两个容器；保留样本、镜像和日志供复核。生产教师应用与课程记录不回滚、不恢复、不删除。

## 本地验证

```powershell
node --test teacher_agent/devtools/onlyoffice-lab/security.test.mjs teacher_agent/devtools/onlyoffice-lab/server.test.mjs
```

真实播放仍须在浏览器验证。安全测试不能替代排版、动画与声音检查。五页测试结果记录在 `TEST-RESULT.md`。
