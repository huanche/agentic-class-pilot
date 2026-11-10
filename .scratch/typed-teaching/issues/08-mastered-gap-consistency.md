# 落实整点评估与有缺口不掌握

Status: resolved

用户已同意实施：提示词明确整知识点评估；mastered且gaps非空统一降为partial，保留缺口、原始评估和原题；partial空gaps不自动升级；5/8限额原样处理。不修改总结格式、教材、其他判答规则，不部署。

沿用已确认的学习命令HTTP接口，先失败后修复；外部模型HTTP替身、独立临时数据库。验证保持当前点、恢复和反馈、合法掌握、首轮/补强限额及原始评估保留。

## Answer

已明确整个知识点评估；推进前mastered+非空gaps按partial应用，保留原题/缺口/原始submitted_assessment，历史result及evaluation使用有效结果。取消掌握分支主动清gap，partial空gap不升级，合法掌握照常，5/8及课后规则不变。接口主用例先Red（任务已消失）后Green，8项命令接口/23项相关回归通过。首次完整回归2条旧样例将mastered+gap当合法掌握，改为真正无缺口，保留原断言；最终完整后端260通过/3跳过。编译、依赖、diff及文档链接通过。未重新真实模型实测，不修教材/JSON，不部署。见[说明](../../../docs/knowledge-teaching/mastery-gap-fix.md)。
