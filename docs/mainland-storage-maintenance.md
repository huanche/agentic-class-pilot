# 大陆服务器存储维护

2026-11-17 排查：177 GiB 系统盘剩余不足 10 GiB。备份约 44 GiB，
其中五份历史快照带 `.keep`；Docker 同时积累了测试、回滚容器和构建缓存。
本次用户授权清理旧备份、无引用历史容器及缓存，保留最新两份备份。

## 本次执行结果

北京时间 2026-11-17 14:46 清理任务成功结束：

- 删除 69 个历史容器，其中 16 个原先仍运行；运行容器从 30 个降至 14 个。
- 删除无容器引用且可移除的候选镜像，清理七天以上构建缓存约 1.69 GB。
- 校验最新两份备份后删除指定五份旧备份，备份占用从 43.59 GiB 降至 16.28 GiB。
- 系统盘可用空间从约 9.8 GiB 增至约 47 GiB，使用率从 95% 降至 73%。
- 平台、学生、教师本机健康接口均 HTTP 200；业务数据卷未删除。
- 审计日志：`journalctl -u agentic-storage-cleanup-20261117.service`。
- 服务器已安装并启用每日维护定时器；仓库中的脚本与单元文件尚未提交。

## 保留规则

- 完整备份继续使用现有策略：校验最新两份后保留这两份，清理其他无保护快照。
- `.keep` 为人工保护，不自动过期。新增保护时应在文件中写明用途、负责人和复核日期；发布验收后复核解除，避免永久累积。
- Docker 每日北京时间 05:00 左右维护；与部署和备份互斥，忙时跳过。
- 只清理停止超过七天的 `agentic-` 容器；保留配置引用的容器，以及各服务最新两份回滚容器。
- 只尝试删除已清理容器使用的镜像。Docker 拒绝删除仍有容器引用的镜像；不使用强制删除。
- 清理七天以上未使用的构建缓存。数据卷、业务文件、运行中的容器不自动清理。
- 每次清理前后检查平台、学生、教师健康接口；详细记录查看 `journalctl -u agentic-storage-maintenance.service`。

## 安装和预演

将 `scripts/mainland/maintenance-storage.py` 安装为 root 所有的
`/usr/local/sbin/agentic-storage-maintenance`，权限 0700；将同目录
`agentic-storage-maintenance.service` 和 `.timer` 安装至 `/etc/systemd/system/`。
执行 `systemctl daemon-reload` 及 `systemctl enable --now agentic-storage-maintenance.timer`。

默认只预演：`python3 /usr/local/sbin/agentic-storage-maintenance`。
实际维护添加 `--apply`。

`--retire-legacy` 和 `--release-historical-backups` 是本次已审计名单的一次性清理选项，
不加入定时器；前者逐个停止历史容器并验证健康，失败则重新启动该容器。
后者校验最新两份备份后，解除五份指定历史快照保护，交给现有备份策略清理。
不将此名单扩展为通配符删除。
