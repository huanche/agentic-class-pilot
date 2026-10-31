# 大陆服务器迁移收尾记录

日期：2026-10-31（北京时间）。此文只记录经过验证的结果；正式公网切换尚未执行。

## 环境与边界

- 香港生产：43.132.155.8，ubuntu，继续承载公网业务；本轮仅执行只读状态和计数核对。
- 大陆：43.138.178.158，VM-0-4-ubuntu，内网地址10.1.0.4，项目/opt/agentic-class-pilot。
- 本机专用SSH密钥：~/.ssh/agentic-mainland-support；用户在大陆root的authorized_keys安装公钥，附带restrict限制。私钥未上传服务器或仓库。
- 原香港SERVER_HOST、SERVER_SSH_KEY及其工作流保持原样。本地学生端未提交修改没有发布。
- 用户已确认继续使用agenticclasspilot.com、腾讯云备案已完成，并明确授权大陆教师端同版本受控替换及成功后开启自动部署。DNS切换仍未执行。
- 大陆平台/学生服务仍保留迁移时的网络隔离；公网Caddy、DNS、证书和应用开机自启尚未切换。

## 已验证的链路

1. GitHub原TCR测试登录成功、上传多层成功，但在1500秒超时，不能视为完整发布成功。
2. 使用大陆已有的已知镜像向TCR补齐基线，随后成功从TCR拉取并核对ID：
   `ccr.ccs.tencentyun.com/agentedu-mainland/agentic-teacher:main-df839c6`。
   ID为`sha256:ff22e32dbb0c0b31cd1ca5edd8447f68238a23016b4fe18a40e3e630caeded9d`。
3. GitHub随后成功发布基线，并构建、推送一个新增小文件层，查询远端manifest成功。测试标签`probe-41190400228`不符合部署标签规则，不能被部署入口使用。大规模依赖更新导致的大层上传仍可能较慢，不能由小层测试推断其稳定耗时。
4. 新的Mainland Teacher Release从原teacher-deploy的成功build复用镜像。只接受本仓库main上的push或手动发布构建，拒绝PR来源；发布前及实际部署前比较teacher_agent目录，拒绝已经被新教师代码取代的版本。
5. 工作流、TCR临时认证、受限SSH、服务器镜像准备和关闭开关时的行为均已通过完整手动运行。
6. 最终本机网关检查：平台首页、学生/app/、教师/teacher/及三端健康接口均HTTP200；教师容器携带现有认证访问DeepSeek模型列表HTTP200，未发起收费生成请求。平台/学生AI调用和真实教学流程尚未做端到端验收。

证据：

- [大陆基线推送/拉取](https://github.com/huanche/agentic-class-pilot/actions/runs/41190097416)
- [GitHub基线及新增层推送](https://github.com/huanche/agentic-class-pilot/actions/runs/41190400228)
- [发布链路验证，容器替换保持关闭](https://github.com/huanche/agentic-class-pilot/actions/runs/41190509306)

## 安全与部署实现

受限用户agentic-ci只允许明确列出的命令，没有普通shell。新增teacher-prepare通过stdin接收小型JSON，固定TCR仓库、校验main-七位hex标签与镜像ID；认证配置仅在/run下root专用临时目录存在，结束时删除。凭据没有持久保存到服务器Docker配置。凭据更新只需维护现有GitHub的TCR_USERNAME/TCR_PASSWORD。

基线引导入口teacher-seed-baseline额外锁定为已验证的main-df839c6及其ID，不能借此发布任意镜像。任意命令id和非法标签请求拒绝测试通过。

部署使用共享锁，镜像准备、备份与部署不能交错。正式部署必须同时满足：

- GitHub变量MAINLAND_AUTODEPLOY_ENABLED为true。
- 大陆/etc/agentic-class-pilot/teacher-deploy-enabled存在且root:root:600。
- 存在root写入的镜像校验记录，当前本地镜像ID与记录一致。
- 完整备份、任务排空、隔离网络、DeepSeek出口和新容器健康检查均通过。

实际运行按已校验镜像ID启动，旧容器保留为回滚容器。失败后尝试恢复旧容器及转发。代码回滚不会自动撤销新版本已经写入的数据或数据库迁移，因此涉及数据格式变化的版本仍需单独制定恢复方案。

隔离故障注入在独立的agentic-teacher-migration-test容器上完成：正常HTTP200版本切换成功，故障HTTP500版本被拒绝，原测试容器ID恢复且健康200。测试未读取生产凭据或挂载业务数据，使用了测试空闲/备份/TLS替身；它验证容器切换状态机，不等同真实新业务版本的端到端验收。

## 备份与恢复证据

备份根目录：/srv/agentedu-auto-backups。

- migration-20261031-174153：首次静止全量备份，SHA256SUMS验证通过；使用.keep保护，切换验收前不自动删除。
- migration-20261031-175322：新版部署前备份程序持锁模式实测通过；完成备份后平台、学生、教师和MinIO恢复。
- 两份备份合计约7.56GiB。保留最近两份成功备份及显式保护的备份；要求至少10GiB可用磁盘空间。

第一次备份已实际恢复到无网络、无宿主机端口的临时PostgreSQL16容器，53张用户表逐表行数与大陆现库一致，恢复容器已清理。教师数据27040个文件、学生运行数据1008个文件、MinIO478个文件均已解包；Git bundle验证通过。之前日志的106包含53行SQL文本，正式统计已修正为53张表。

运维配置补充备份覆盖systemd、受限SSH脚本、sudoers、教师/学生环境等，目录仅root可读。数据库备份可能包含账号和认证材料，不能作为公开附件上传。

备份审计及恢复结果：/srv/agentic-migration-audit/20261031。后续配置补充归档：/srv/agentedu-server-config-backups。

备份程序/usr/local/sbin/agentic-mainland-backup会停止大陆入口、等待教师任务结束、停止写入者，再做PG/MinIO/教师/学生/源码/配置备份，最后恢复先前运行的服务。本轮一次完整过程约4分钟；未来数据增多可能变长。定时器设为每天北京时间03:30；重启后不会立即补跑错过的任务，避免白天突然停服务。原6GiB软告警低于实测两份备份大小，已调为20GiB；10GiB最低可用空间门槛保持不变。

备份仍位于同一台服务器，尚无异地副本。回滚容器也不替代数据备份。

## 上线前仍需完成

1. 大陆正式教师受控替换已获用户授权；实际执行结果和开启状态见文末后续记录。
2. 大陆平台和学生端目前与香港源码提交一致，均为ed8d193；但它们的大陆main自动部署尚未接入，新工作流仅覆盖教师镜像。
3. 保持香港为唯一写入源，确定停写窗口后重新同步最新PG、MinIO及文件，验证后才切换入口。当前已观察到香港browser_session计数563、大陆562，不能把快照当实时同步；其他已抽查的主要学习/课程计数一致也不代表逐内容一致。
4. 平台/学生AI出站仍受迁移隔离限制，须在受控解除隔离后验证真实业务、登录、课程发布、学生学习、对象上传下载、语音和AI调用。
5. 已生成并通过Caddy2.10配置校验的Caddyfile.production-candidate，明确监听10.1.0.4，避免与172.19.0.1:443的教师DeepSeek代理争用。它尚未启用，也未申请证书。
6. 核对公网域名及腾讯云大陆备案/接入备案、云防火墙和HTTPS、邮件配置、应用端口仅本地可达、服务开机自启与重启恢复。腾讯云[官方说明](https://cloud.tencent.cn/document/faq/243/20220)要求大陆网站在备案完成后开通访问。
7. 先使用受控预览入口完成三端业务验收，再安排DNS切换。DNS回切期间必须防止两边写入；若大陆已经写入新数据，不能仅改DNS就宣称数据已回滚。

## 常用只读检查

```bash
/usr/local/sbin/agentic-teacher-deploy check
systemctl is-active agentic-platform agentic-student agentic-teacher-forward agentic-deepseek-egress
systemctl list-timers agentic-mainland-backup.timer
journalctl -u agentic-mainland-backup.service -n 40 --no-pager
df -h /
```

手动完整备份（会短暂暂停大陆应用）：

```bash
sudo /usr/local/sbin/agentic-mainland-backup
```

禁用大陆教师自动替换时，先把GitHub变量设为false，再移除大陆保护文件；在途部署需要先检查运行状态，不能把关闭开关当作中断或数据回滚。不要修改香港的Secrets。
