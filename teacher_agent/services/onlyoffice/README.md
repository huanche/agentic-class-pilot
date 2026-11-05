# ONLYOFFICE 高保真播放

正式入口由 `SceneRenderer` 选择：新高保真 PPTX 任务会保存原文件快照及原始页码、完整点击序列，播放时显示 ONLYOFFICE 只读放映。AI 增强及没有原文件快照的旧课件继续用网页画布。

生成任务先在服务器核对课程材料 SHA-256，再保存 `classrooms/<id>/native/source.pptx`。删除或重排大纲只改变场景顺序，原稿页码按 outline 身份保留。材料替换不会修改既有快照。修改网页画布会标记该页已编辑，使它显示老师修改后的内容；单独重新生成讲解保留原稿绑定。

原稿 `subTnLst` 的 `nextClick` 隐藏转换为下一组既有点击中的显式退出，不改文字、形状或增加点击。读取完整主序列，不能以旧网页导入器支持的动画数量代替原稿点击数量。原稿专用动作与旧画布可识别动作分开保留，切回兼容播放器时不会执行假的整页动画。

配音沿用课堂的 Kokoro/TTS 与音频实际结束事件。原稿换页和动画完成前，动作引擎不会越过对应步骤。原稿对象不套用旧画布坐标的聚光/激光效果。暂停、继续、停止和回放跳转通过固定的只读方法桥接。

## 运行

服务目录只依赖 Node 核心库；`pptx-compat.mjs` 由教师服务生成任务调用，使用既有 JSZip 和 XML 依赖。运行时配置放在 `/var/lib/agentic-onlyoffice-player/config.json`，权限 600，不进入仓库：

- `publicOrigin`：正式 HTTPS 域名。
- `jwtSecret`：与私有 DocumentServer 匹配的独立 JWT 密钥。
- `nativeEnabled`：运行时开关；默认 false，检查后启用。

`TEACHER_INTERNAL_URL` 固定私网教师地址，`CLASSROOMS_ROOT` 只读挂载课堂文件。服务沿用平台 Cookie 或平台既有服务委托认证，每个配置请求都交给教师接口重新验证课堂归属。不接受任意文档 URL、任意磁盘路径或任意编辑器方法。文档下载与插件配置使用短期、绑定具体资源的能力签名。

网关 `/onlyoffice/*` 转发此服务；`/onlyoffice-engine/*` 继续转发现有私网 DocumentServer。两个容器均不映射公网端口。

插件配置与入口位于同一个短期 session 目录。ONLYOFFICE 10 的 `getPlugins` 会根据配置 URL 重设 `baseUrl`，因此 variation 的 `url` 必须为相对的 `index.html`，不能再次包含 `session/<nonce>/`；否则目录重复、插件入口404，父页面一直等不到就绪消息。服务测试会按引擎的真实地址解析方式请求入口，并保留语言和主题参数。

## 回退

高保真原稿页只提供 ONLYOFFICE 预览和播放，加载错误后提供“重新加载”，不提供切换兼容播放器的入口。`cloud-toggle.sh disable` 用于维护时关闭原稿服务，页面会显示服务不可用并允许重试，不再自动切换网页画布。没有数据库结构迁移，不需要恢复课程数据。

如果需要回退教师镜像，使用部署时保存的旧教师容器和配置，只更换程序；保留新原稿快照及课堂内容。不要使用旧实验的 `cloud-stop.sh` 停止被正式服务共用的 DocumentServer，该脚本已增加依赖保护。

## 检查

```text
node --test services/onlyoffice/pptx-compat.test.mjs services/onlyoffice/server.test.mjs
vitest run tests/action/onlyoffice-native.test.ts tests/server/native-pptx-source.test.ts
```

这些检查覆盖身份、签名、快照、点击绑定与控制语义，不代替真实浏览器中的五页连续播放和听音验收。
