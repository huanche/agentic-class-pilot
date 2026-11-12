# 含糊与跑题组结果

| 场景 | 状态 | 已提交作答 | 真实请求 | 结果 |
|---|---|---:|---:|---|
| [vague](vague/README.md) | completed | 4 | 13 | 2点被判掌握 |
| [offtopic](offtopic/README.md) | failed | 3 + 1失败未提交 | 13 | 1点被判掌握 |
| [offtopic-recovery](offtopic-recovery/README.md) | completed | 7 | 22 | 2点被判掌握 |

核心问题：局部回答被判整个知识点掌握；原跑题场未触发人设且出现算术错误、非JSON回复中断；补场实际反问/疲劳可被回应，但依然提前判全点并让总结与State不一致。没有进入补强。
