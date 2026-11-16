# 学生端正式发布记录：2026-11-03

用户授权按照已审核方案推送 main、关闭自动激活、安装运维脚本、停写备份、迁移并验收后开放入口。本次正式发布已完成。

## 发布结果

| 项目 | 结果 |
| --- | --- |
| 正式业务代码 | `370c2e261488892fd6ba8519d39c01e89f45bb75` |
| 云端构建和测试 | [Mainland Web Release 41585343534](https://github.com/huanche/agentic-class-pilot/actions/runs/41585343534)，success；自动激活未执行 |
| 生产版本目录 | `/opt/agentic-mainland-web/releases/370c2e261488892fd6ba8519d39c01e89f45bb75`，平台/学生工作目录均已切换 |
| 数据库 | `pub10 → cmd11 → rec12`；242 个历史会话回填，快照/状态版本/内容代际核对差异为 0 |
| 动态教学 | `STUDENT_DYNAMIC_PILOT_SCOPES=[]`；公网 readiness 返回 `dynamicTeachingClosed=true` |
| 维护窗口 | 北京时间 13:49:35 开始，14:23:58 验收并开放；主要耗时为完整文件备份及异机传输 |
| 自动激活 | MAINLAND_WEB_AUTODEPLOY_ENABLED=false、MAINLAND_AUTODEPLOY_ENABLED=false；香港发布维持 false |
| 定时器/服务 | 原备份与教师恢复定时器已恢复 active；平台、学生、原教师上游运行正常；无失败 systemd 单元 |

## 备份和恢复证据

- 停写基线：`/srv/agentedu-auto-backups/migration-20261103-135119`，pub10，已加 `.keep` 保护。
- 迁移后备份：`/srv/agentedu-auto-backups/migration-20261103-141517`；不能用其中旧代码目录直接回退新格式数据。
- 本次枚举并停止了平台、学生及 13 个共享正式数据目录的容器，教师生成队列确认无 queued/running 后才备份。
- 在 `--network none` 的临时 PostgreSQL 中恢复真实备份，53 张业务表行数全部匹配；教师文件 28687、学生 runtime 文件 1008、对象存储文件 478 恢复验证通过，临时数据库容器已清理。
- 香港独立受限目录 `/srv/agentic-student-release/20261103-370c2e2` 保存停写数据副本：15 个 manifest 文件逐文件 SHA256 验证通过，归档 4847472640 字节；另有配置与原运维文件副本，5 个文件校验通过。没有在香港恢复或启动旧业务。
- 大陆同路径为 root-only 审计目录，保存维护状态、原 Caddy 配置、运维文件备份、迁移和验收结果及恢复证据。备份含敏感资料，不上传仓库；临时冻结的两端运行环境已从 `/run` 精确清理。

## 验收

使用专用学生验收账号及真实已发布课时，未借用现有学生账号或修改其作答记录。通过：平台真实登录、课程授权/课时进入、legacy 教学开场与真实模型回答、同一回答命令重复提交仍仅保存一次、历史恢复、版本化内容和学习记录读取、结束反馈及再次恢复、无效令牌拒绝。学习进度 outbox 已完成同步；验收账号随后停用、其临时选课已移除，记录留作受限审计。

开放前恢复原教师容器和上游；恢复时发现动态分配容器占用了 OnlyOffice 容器声明的固定 IP，已先启动固定 IP 容器，再启动动态容器并刷新教师转发，保持原镜像和数据。验收脚本中目录加载及消息字段假设已按实际 API 修正，不涉及业务代码变更。

开放后从公网（TLS 正常）再次确认以下均为 HTTP 200，且 `X-Agentic-Backend=mainland`：`/`、`/app/`、`/api/v1/utils/health-check/`、`/api/session/ready`、`/api/health`。readiness 返回 `ok=true`、`dynamicTeachingClosed=true`。

## 后续操作边界

- 保持自动激活关闭。下次发布仍需检查候选 revision、受限角色 readiness 和数据格式兼容声明；不能把发布 main 等同于允许自动迁移数据库。
- 如需回退，保留新命令/证据/课时内容，使用兼容 rec12 的版本。不得重启旧写入实现、直接 downgrade、用香港旧快照覆盖新增数据或只修改 DNS。
- 后续停写备份必须覆盖共享数据容器，并按固定 IP 优先恢复。本次已人工完整覆盖；现有定时备份 wrapper 只管理固定的主服务集合，尚未实现对后来新增共享容器的自动枚举，后续需补齐这项运维改造，不能把本次成功视为未来定时备份已自动覆盖所有写入者的证明。
- 本次为明确窗口创建异机副本，不代表已建立持续异地备份策略。
