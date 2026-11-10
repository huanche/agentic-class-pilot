# 程序选择教学目标和动作，最终直接回复中文

Status: resolved

用户确认分工后授权按Matt技能实施。使用codebase-design/tdd，沿用已确认的学习命令HTTP接口。先复现自然中文开场/总结被JSON解析拒绝，再实现。

新会话reply_version=1：评估工具仍结构化提交；程序固定选择当前点第一项未完成要求及ask/clarify/explain/correct/summarize动作；最终回复仅非空中文，不解析question/target_ids/assistance。实际全文保存为原题（首次）、后续提问和帮助记录，计划动作单独标记，不断言实际发生了某类帮助。旧会话继续原协议，5/8与逐项掌握不变。

保留之前未提交的提取提示词及验证，不混入回退、提交或部署。

## Answer

自然中文开场/总结先Red→Green；计划记录错误标为model_reported_help也先Red→Green，改为unclassified_tutor_text、guidedPolicy=null与单独plannedAction。程序第一未完成目标选择不受模型next_step建议影响；实际全文、原题和要求证据跨课后恢复，空回复失败回滚及重试、含糊回答选择clarify均经HTTP验证。

完整后端273通过/7跳过（2平台专库、1旧教学真实模型、4提取真实模型），编译/依赖/diff通过；没有重跑真实模型，没有修改提取改动或教材，没有提交部署。旧会话不自动加入reply_version，新建会话启用。结构修复不保证模型语义判答或实际回复完全遵循计划。
