# 复合要求的证据仍有宽判风险

Status: needs-triage

在逐项进度实现后的真实模型抽样中，链队列understandingPoints:2是“入队：在rear之后插入，无队满问题”。学生只说明头尾指针和动态分配没有固定队满，模型仍确认整项demonstrated，缺少插入位置的直接说明。

追加“复合要求须整体满足”的提示后，使用原问题、原回答与原前置State定向回放，仍宽判。保留失败，不能宣称增加逐项结构就解决了全部判答质量。

后续需要讨论/验证复合要求应如何表达、累计哪些证据可以支持推断；不能退回整点mastered开关，也不能简单要求学生逐字复述。尚未增加新业务规则或独立语义审核。

证据：[本轮报告](../../../docs/knowledge-teaching/validation/2026-11-10-requirement-progress/README.md)、同目录compound-item-probe.json和run-artifact-error.json。
