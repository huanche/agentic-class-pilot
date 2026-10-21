# 生产服务器本机备份规则

全量备份目录为 `/opt/agentic-class-pilot/.runtime/backups`，只保留最近两份完成且校验通过的备份。新备份失败不替代旧备份。保留的两份校验失败时停止整个清理，交由人工检查。

普通代码、页面和提示词发布不创建全量备份。平台部署检测到 Alembic 待执行迁移时，先备份数据库、教师数据、学生运行数据、对象存储、源码及配置；备份失败不执行迁移。手动执行数据迁移、存储调整前，也必须运行下面的 `backup` 命令并确认成功。

```sh
sudo python3 /usr/local/lib/agentic-class-pilot/server-backup-policy.py plan
sudo python3 /usr/local/lib/agentic-class-pilot/server-backup-policy.py apply
sudo python3 /usr/local/lib/agentic-class-pilot/server-backup-policy.py backup
```

`backup` 先清理合规历史备份，剩余不足 10GiB 时拒绝创建新备份。过程中使用互斥锁，成功后生成 SHA256 清单及完成标记，校验后再清理旧备份。数据归档期间应避免写入；脚本不是跨数据库与对象存储的事务快照，重要数据迁移应在维护窗口运行。

每小时执行保留任务。正在被进程打开的目录、带有 `.keep`、`KEEP`、`PROTECTED` 或 `BACKUP_IN_PROGRESS` 标记的目录不删除。需要长期保护时，在对应备份目录中创建 `PROTECTED` 文件。未完成备份超过24小时且无进程占用后可清理。人工备份也应使用上述命令，避免清理与备份并发；失败遗留的 `BACKUP_IN_PROGRESS` 标记需人工确认任务结束后移除。

备份超过 6GiB 时写入告警日志；受保护目录不会为了满足预算被强制删除。查看日志：`journalctl -u agentic-backup-retention.service`；查看定时器：`systemctl status agentic-backup-retention.timer`。

前端产物保留两个历史版本；教师镜像保留当前及两个成功历史版本，仅清理同一项目的旧部署标签。Docker 卷、数据库和当前运行镜像不纳入备份目录清理。

安装：将脚本安装到上述固定路径（root所有、0755），使用 root 的 systemd oneshot 服务执行 `apply`，定时器每小时运行。
