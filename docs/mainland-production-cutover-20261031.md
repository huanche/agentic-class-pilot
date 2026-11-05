# 正式业务切换记录：2026-10-31

**三端业务及域名权威解析均已切到大陆43.138.178.158。香港只做HTTPS兼容转发，原应用已停写。**

## 当前生产位置

| 项目 | 当前状态 |
| --- | --- |
| 唯一业务后端 | 大陆43.138.178.158，VM-0-4-ubuntu |
| 平台/学生 | /opt/agentic-mainland-web/current内的独立版本，systemd运行 |
| 教师 | 大陆agentic-teacher-prod，镜像按已校验ID运行 |
| 正式HTTPS网关 | agentic-caddy-preview.service（沿用历史名称，现已承担正式流量） |
| 网关配置 | /etc/agentic-class-pilot/Caddyfile.preview（沿用名称，预览来源限制已移除） |
| 香港43.132.155.8 | 网关转发到大陆；平台/学生停止并禁用自启，教师和MinIO停止 |
| 公共域名 | agenticclasspilot.com；两个权威DNS均仅返回43.138.178.158，旧缓存请求由香港转发 |

## 已完成的切换

1. 用户明确授权进入正式窗口。暂停大陆发布/备份，持维护锁；旧香港5个部署job改为仅HONGKONG_DEPLOY_ENABLED=true时执行，当前为false。原SSH Secrets保留，teacher构建仍可供大陆发布复用。
2. 完成大陆切换前完整备份，香港进入维护页；两次确认教师无排队/运行任务，再优雅停止写入服务。香港WRITERS_STOPPED记录时间19:43:10。
3. 停写状态下重新核对全部文件，流式传输最终差异、数据库角色及education自定义格式转储；没有把私钥、密钥或数据库内容输出到聊天/仓库。
4. 传输SHA256与接收端完全一致。数据库转储110682263字节，角色资料1564字节，压缩文件差异5909字节。补齐源端角色，保留大陆运维角色。
5. 恢复后，教师27040、学生runtime1008、MinIO466个文件均与冻结源端内容一致。53张用户表逐表行数及内容指纹全部匹配；这是应用启动、正式写入前的比对。
6. 启动大陆，复验三端健康、教师/学生认证、5组已发布课程入口与学习目录、S3对象读取及AI认证通过。随后打开大陆正式入口。
7. 香港网关19:48:59启用大陆转发，业务恢复；新旧解析缓存都访问同一个大陆后端，香港不再运行旧应用接受写入。
8. [独立公网验证](https://github.com/huanche/agentic-class-pilot/actions/runs/41198659528)通过：两个IP各6个三端页面/健康入口均HTTP200、TLS校验成功，响应X-Agentic-Backend为mainland。
9. 19:55:54释放维护锁、恢复大陆发布和定时备份。两个大陆发布变量为true，服务器保护文件root:root:600；当前无失败systemd单元。

语音附加核对：两端Kokoro/Hojo镜像ID一致，运行目录没有源端缺失文件。Kokoro仅ONNX运行时遥测SQLite的WAL/SHM不同，未覆盖大陆运行中的缓存；Hojo运行目录均无自定义文件。备份策略已纳入两语音运行目录，排除上述可再生遥测缓存，覆盖以后保存的音色资料。

## DNS变更与最终核验

在DNSPod修改现有记录：

| 字段 | 目标 |
| --- | --- |
| 域名 | agenticclasspilot.com |
| 主机记录 | @ |
| 类型 | A |
| 原地址 | 43.132.155.8 |
| 新地址 | 43.138.178.158 |
| TTL | 保持600秒原值即可 |

公共查询未发现AAAA记录。用户修改期间短暂出现新旧两条A记录；清理旧记录后，两个权威服务器balsam.dnspod.net和thunder.dnspod.net均已验证仅返回43.138.178.158，完成标记存于大陆/srv/agentic-cutover/20261031/DNS_AUTHORITATIVE_VERIFIED。

部分递归DNS或客户端缓存暂时保留旧IP不会形成第二写入点，香港兼容代理仍转发大陆。三端页面及健康接口均HTTP200、TLS有效，当前无失败systemd单元。确认解析和业务稳定后再安排香港下线。

## 发布和维护

学生端可靠会话升级的最新门禁、停写迁移和回退限制见 [2026-11-03 上线前检查](../student_agent/.personal-dev/docs/student-production-preflight-20261103.md)。该文列出的运维脚本与迁移尚未安装/执行；不能将本节历史切换验收当作本次新版本已可直接上线的证明。

- main上teacher_agent变动走teacher构建、TCR、受限SSH教师发布；platform或student_agent变动走独立web构建/测试和TCR版本发布。数据库revision变化会阻止web自动上线，需单独审核迁移。
- GitHub变量：MAINLAND_AUTODEPLOY_ENABLED=true、MAINLAND_WEB_AUTODEPLOY_ENABLED=true、HONGKONG_DEPLOY_ENABLED=false。
- 不要把旧SERVER_HOST/SERVER_SSH_KEY改为大陆。大陆使用MAINLAND_*专用通道，旧香港工作流已停用部署步骤。
- 应用发布会先等待教师任务并执行完整静止备份。本轮完整过程约4分钟，数据增大时会更长；每天北京时间03:30的备份也会短暂暂停大陆应用。
- 当前域名、API路径、JWT/服务认证密钥保持兼容，原账号和课程数据已同步。后续维护以大陆为准，香港数据库是停写快照。
- 目前保留香港停写源站及大陆本机备份；尚未建立新写入的持续异地备份。

## 审计与回退边界

大陆/srv/agentic-cutover/20261031保存最终数据库/角色转储、文件清单、逐表指纹和完成标记；/srv/agentedu-auto-backups保存完整备份。目录包含敏感资料，只限root。

香港/srv/agentic-cutover/20261031保存原Caddyfile、原服务启用状态和切换时间。原数据保留，网关配置现为经过TLS校验的大陆反向代理。

大陆已接受正式流量，**不能再从停写的香港直接覆盖大陆数据库，也不能只改回DNS就宣称数据已回滚**。如需退回香港，必须先冻结大陆、处理新增数据并验证一致性。此次一次性同步程序已加入上线标记防护，避免误重跑覆盖在线数据。
