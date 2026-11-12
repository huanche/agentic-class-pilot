# 学生端文档与剩余验证记录收尾

按用户要求，将本次学生端教学方案、新提取验证和全部相关测试证据归入学生端目录：

- `student_agent/docs/knowledge-teaching/`
- `student_agent/docs/knowledge-extraction/`
- `student_agent/evidence/`

不再放入根目录 `docs/knowledge-teaching`、`docs/knowledge-extraction` 或 `evidence`。早期已归档的 `.personal-dev/docs` 保留原位置；它仍位于学生端目录中。

合并提交了此前未提交的“编程题答错→退出→续学→等价正确解→完成”组合测试及原始验证记录。根目录三份混合日志尚未提交的追加内容分别归档到本目录的 findings/progress/task_plan 记录，保留历史主日志，仅更新相关搬迁链接。

搬迁核对：447份原文件均存在于新位置；147个相对文档链接、43份Python脚本语法及凭据扫描通过。修正报告链接、读取路径、输出目录与6份脚本的仓库根目录定位；原始JSON模型输出不改写，保留当时输入输出与失败。

迁移后回归：75 passed、11 skipped（139.23秒）。跳过的是默认关闭的真实模型测试，本次没有重新调用模型；组合测试此前的真实执行结果已随证据归档。运行时业务实现不变。

统一入口：[教学文档索引](../README.md)与[学生端目录说明](../../student-directory-layout.md)。
