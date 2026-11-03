# 学生端上线前检查：2026-11-03

基线：本地提交 `7c054ea88d8b32fafb197f1a1ce32e2848fa36f0`。结论：**暂不能直接上线，需要一次明确的停写迁移窗口**。本次只读访问生产并修复本地代码，没有部署、上传、迁移、重启生产，也没有修改 GitHub 变量。

## 已核实的生产事实

| 项目 | 只读检查结果 |
| --- | --- |
| 实际生产 | 大陆 `43.138.178.158`；平台与学生 systemd 服务均 active |
| 当前代码 | `/opt/agentic-mainland-web/releases/8729686e1c0a318e41219f7e7cd65612306a96fd` |
| 数据库 revision | `pub10`；本地 Alembic 唯一 head 为 `rec12`，依次经 `cmd11` |
| 新表 | 生产尚无 `student_commands`、`pending_progress_sync`、`lesson_content_versions` |
| 动态教学 | 运行进程准入配置为空，当前关闭；本次不改变已有会话的存储 flow |
| 认证与地址 | 两端 STUDENT_SERVICE_KEY 非空且一致；学生 PLATFORM_AUTH_URL 指向 `http://127.0.0.1:8080/api/v1`；平台 STUDENT_URL 未显式覆盖，代码默认 `http://127.0.0.1:8000` |
| 数据库角色 | schema owner 为 platform；student 不是超级用户，现有学生表 SELECT/INSERT/UPDATE 权限正常 |
| 回填数据初检 | 最新 agent_state 共 242 个会话；版本字段未发现不符合非负 18 位整数规则的值。此规则比 bigint 更保守，只是初检，不能替代正式迁移 |
| 备份 | 发现 3 个 BACKUP_COMPLETE，最新 `migration-20261102-095415`。只检查完成标记，没有在生产恢复或据此宣称备份已可恢复 |
| GitHub 发布变量 | MAINLAND_WEB_AUTODEPLOY_ENABLED=true；HONGKONG_DEPLOY_ENABLED=false |
| 安装的 web 发布器 | 与本次修改前的仓库脚本 SHA256 一致，因此服务器仍使用旧发布/回退逻辑 |

学生角色无权读取 public.alembic_version 是正常隔离；revision 使用 platform 连接只读核实。未输出凭据或学生记录内容。

## 本地修复

1. 保留 `/api/session/health` 行为，新增 `/api/session/ready` 及 `python -m backend.infrastructure.release_check`。使用学生运行角色、只读事务及连接/语句超时检查关键列、索引有效性、DML/序列权限，以及课时内容不可 UPDATE/DELETE；错误仅返回固定代码，不输出连接串。不调用模型。
2. 本次发布要求动态准入严格为空；无效 JSON 也拒绝就绪。启动脚本显式固定 `STUDENT_DYNAMIC_PILOT_SCOPES=[]`，生产配置示例同步说明。未来开启动态教学需要单独调整发布策略，不能直接修改试点配置后忽略就绪失败。
3. 发布前仍要求 revision=head，不自动执行迁移；切换前运行受限角色预检，切换后检查 readiness。
4. 新增 `RELEASE_COMPATIBILITY.json` 声明可靠命令/记录数据格式。只有前后版本都声明相同格式，才自动恢复旧服务。首次升级失败会停止平台和学生写入，保留数据，拒绝自动启动当前生产的旧实现。声明是维护者的兼容性承诺，禁止给旧实现补一个标记绕过检查。
5. 新增 root-only `--stage-only SHA` 预备代码和依赖，不迁移、不备份、不停服务；root-only staging receipt 校验镜像 ID、SHA 和原版本，允许迁移后重试使用完整候选目录。不完整/不可信目录仍须人工检查。
6. 新增 root-only `--capture-migration-environment`，把当前两端环境保存在 `/run/agentic-web-migration`，目录 0700、文件 0600，绑定原版本。旧服务停止时从可信文件读取配置，避免为发布重启旧写入进程。文件含密钥，禁止上传、打印、放入 release 或仓库。
7. CI 激活改用受限 `web-deploy-v2 SHA DEPLOYER_SHA256`；服务端核对已安装发布器摘要。旧服务器入口会拒绝此新命令，必须先安装审核后的运维脚本与 sudoers，不能只发业务代码就认为保护已生效。
8. 两条学生相关 CI 增加隔离 PostgreSQL 17 和 STUDENT_TEST_DATABASE_URL，避免数据库回归静默跳过；增加前端单元测试。扩展大陆工作流的脚本变更触发及候选代码一致性检查。
9. 复核最近一次大陆发布失败日志（run 41398718949）：uv 继承 CI 用户目录，切换 ubuntu 后读取 `/home/agentic-ci/uv.toml` 被拒绝。为 uv 检查、建环境和安装显式指定候选应用工作目录；新增真实 Linux 临时目录回归，禁止调用生产 systemctl/Docker/数据库。
10. 首次激活失败可能使 current 已切换但服务仍停止；修复从 root-owned staging receipt 核实上一版本环境的读取，允许准备兼容修复版本，不必重新启动旧写入进程。不可信 receipt 仍拒绝。

旧香港发布路径保持禁用，不作为本次发布或回退路线。

## 正式窗口的执行顺序（本次未执行）

以下步骤属于另一次获准的生产维护，不是现在的部署指令。目标 SHA 必须包含本次修复并通过 CI，不能使用不含修复的 7c054ea 直接激活。

1. 先关闭 GitHub web 自动激活，核对无在途发布，准备网关维护入口、候选镜像和兼容修复方案。现有 MAINLAND_WEB_AUTODEPLOY_ENABLED=true，后续推送 main 可能触发发布任务，不能把“本地提交”当成“安全推送”。保持香港发布关闭。
2. 备份当前运维文件；以 root 安装本次 `agentic-web-deploy`、`agentic-mainland-ci-entry`、`agentic-mainland-ci-root`；先对 sudoers 示例 `visudo -cf` 再安装为 root:root 0440。保留教师和 web-prepare 的原受限授权，增加 web-deploy-v2；旧 web-deploy 在新 root wrapper 中不再可用。核对 LF 换行、可执行权限及发布器 SHA256。**本次未在生产安装这些文件。**
3. 当前服务仍运行时，root 执行 `/usr/local/sbin/agentic-web-deploy --stage-only "$TARGET_SHA"`，确认 `WEB_STAGED_ONLY`，目录和依赖齐全。此步骤不启动新代码，不回填数据库，不接受新格式写入。
4. 关闭业务写入口并排空在途请求；root 执行 `--capture-migration-environment`。检查保存成功且绑定当前版本，然后停止 agentic-platform 与 agentic-student，确认 MainPID=0。后台进程也算写入者，不能仅关浏览器入口。已有 /run 文件需先核对上次窗口，禁止不经检查覆盖。
5. 持 `/run/lock/agentic-teacher-deploy.lock` 的 fd9 维护锁，确认无其他写入进程，再运行 `/usr/local/sbin/agentic-mainland-backup --locked`。它只恢复原先 active 的 systemd 单元，平台/学生在调用前已停，因此应保持停止。核对这一份 **pub10 停写快照** 的数据库、runtime 和配置备份、校验和与恢复材料。不要用昨日备份代替本窗口快照；将新快照复制到独立备份位置并验证可读性。
6. 使用候选 `platform/.venv/bin/python`，工作目录为候选 `platform/backend`，通过冻结的 platform 环境（不在命令行传密码）运行 `python -m alembic current`，确认 pub10；再 `python -m alembic upgrade rec12`，复核 current/head 均为 rec12。应设置合理 lock_timeout/statement_timeout，锁等待或回填错误时中止，保持停写，先排查，不并行启动旧服务。
7. 使用冻结的 student 环境及候选学生解释器运行 `-m backend.infrastructure.release_check`，必须通过。核对回填会话数量、快照、版本值、撤销状态、命令唯一约束和受限角色权限；不要用 migration owner 代替学生角色做验收。
8. 确认自动激活仍关闭；释放人工维护锁后，由唯一操作员激活同一候选 SHA。发布器自行取得同一把锁，复用已验证候选；不要在持锁的父 shell 中再次调用会自行 flock 的发布器。它会做迁移后备份并启动新服务；该备份不能代替第5步的 pub10 回退快照。
9. 保持维护入口，检查三端认证/入口，学生 readiness、一次现有教学回答和重试/恢复，确认动态准入仍关闭。通过后开放入口、核对写入和备份状态。两份 /run 环境文件在恢复无误后按精确路径安全移除，后续窗口重新捕获；需要恢复自动激活时再明确操作。

候选环境执行命令时，可由 root 读取 `/run/agentic-web-migration/agentic-platform.json` 的 environment，经受控子进程传给 runuser/候选解释器；学生检查同理。不得通过 shell echo、日志、命令参数展示环境内容。连接信息仅留在受限环境中。

## 失败与回退边界

| 失败阶段 | 处理 |
| --- | --- |
| staging / revision / readiness 前置检查 | 不切 current、不启动新服务。修复后重试；完整候选由可信 receipt 识别，不完整目录人工检查 |
| 迁移失败 | PostgreSQL 事务应回滚本次升级；核对实际 revision 与列/表后重试。停写和维护入口继续保持，不将失败当作可安全启动旧服务的证明 |
| 已迁移、尚无任何新写入，需要取消整个窗口 | 先确认全站仍停写，再按审批方案恢复同一窗口的 pub10 数据库、runtime、配置和原应用；在隔离恢复副本先验证，再验收后开放。不能仅运行 alembic downgrade |
| 首次新版本已尝试启动或已写入 | 禁止直接切回生产旧版本、覆盖旧快照、改香港 DNS 或删新表。保持维护和停写，保全日志/新记录，使用兼容 rec12/可靠命令的修复版本恢复；如需重建数据库，必须先处理新增数据并另行审核 |
| 以后两个版本都兼容可靠记录格式 | 发布器可恢复原 drop-in、current 和服务，并复核 readiness；不执行数据库 downgrade，不删除命令、证据或课时内容 |

cmd11/rec12 的 downgrade 为保留数据而不删除表，但 Alembic 会改变 revision 标记；因此 **downgrade 不是本次数据回退办法**。没有验证恢复材料就不开放正式写入口。目前只观察到同机备份，不能据此认定持续异地备份已建立。

## 本地验证与限制

- 最终后端完整回归 **189 项通过**，使用专用 loopback PostgreSQL 17 集群，测试只创建/删除随机测试数据库。
- 前端单元测试 **42 项**、Playwright 流程测试 **17 项**、学生前端生产构建通过。
- 真实 Alembic revision 文件在隔离库执行 pub10→cmd11→rec12，验证历史快照回填、非法版本导致原子回滚、修正后重试及重复升到 head。测试使用最小连接环境，未执行生产 env.py 或迁移生产数据库。
- 验证受限学生角色通过预检，缺权限、可变课时内容、缺列、动态准入非空/无效均拒绝；验证不兼容回退只停写、不启动旧实现。
- 额外使用平台真实 `alembic.ini/env.py` 和平台依赖环境在独立合成库完成 pub10→rec12 及旧快照回填；强制禁用 dotenv、显式指向临时 loopback 数据库，没有读取生产配置或迁移生产。
- 使用同版本 PostgreSQL 17 工具对合成会话、pending 命令、版本化内容进行 pg_dump/pg_restore，校验数据和关键索引恢复。恢复演练跳过 owner/ACL，权限另由迁移/受限角色测试核对；未恢复生产备份，不能代替正式窗口的恢复验证。
- 通过 SSH stdin 在大陆 Linux 执行 **10 项隔离发布器测试**：仅操作自动清理的临时目录，所有 subprocess/健康请求替换为模拟实现，未安装脚本或调用生产控制命令。覆盖 staging、revision/readiness 拒绝、旧写入者保护、成功顺序、首次失败停写、兼容回退、冻结环境、失败后修复与 uv 工作目录。相同测试已接入 CI。
- Bash 语法、Python/YAML 检查、LF 源文件经 Linux `visudo -cf /dev/stdin` 校验通过。Linux systemd/SSH/sudoers 的正式安装、新 CI 云端运行和生产备份恢复尚未执行，这些属于正式窗口待验项。
- 未改变教学规则、前端交互或模型行为；真实动态回答/求助稳定性仍沿用本地验收中的未通过记录，本次不开放动态教学。
