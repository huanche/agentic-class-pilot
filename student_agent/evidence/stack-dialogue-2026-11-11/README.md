# 本地真实会话：重复要求复述因果与突然切点

从本机学生库只读定位截图对应记录，保存脱离账号及会话身份的dialogue.json；未改写用户数据库或历史进度。课程实际点为concept“栈与队列作为受限线性表”，不是memory。

## 实际原因与复现

学生第一轮确有把栈也写成先进先出的矛盾，针对该错误的首次纠正合理。第二轮已改正并说明操作位置；第三轮给出栈CBA、队列ABC；第四轮补“栈只能在栈顶删、队列只能在队头删”。模型没有有效合并这些正确的学生作答，仍要求按指定句式重述关系。第五轮学生说不知道并请求直接讲解，程序达到首轮5次上限换点，生成上下文却只给上一点id/title/status/evidence，无法可靠完成旧题收尾。

replay.py以实际记录重建第4、第5轮前的状态，经当前typed_teaching.run真实调用deepseek-v4-flash，不写入业务库。baseline.json复现：第4轮仍needs_help并再问C/A原因，第5轮只有泛泛回顾，未回答具体求助。离线两个调用者接口回归在修复前分别因previousPoint缺type/latest_question失败。

## 最小修正

- 评估明确合并本点多轮学生依据：已给出正确顺序，随后补出决定顺序的操作限制，可以共同体现关系，不强求同一句重述整条链或样例字母；仍拒绝只有术语、矛盾或缺少关键关系的表现。
- natural回复切点时，previousPoint临时上下文补type/details/known_parts/gaps/latest_question，不添加持久化字段或旧点完整历史。先回答具体求助，再引入新点，不追加旧题或轮数，不把讲解算成掌握。
- 删除与收尾相冲突的“只简短反馈旧点”指令，说明新点类型策略仅用于新问题。

没有变更选点顺序、5/8限额、全部要求完成才掌握的程序规则，没有自动回填历史掌握。

## 验证

第一次修改after.json成功，但verified.json复跑中收尾仍只泛泛总结，人工复核未通过。该输出原样保留，不能把脚本仅检查累计掌握的退出0当成整个问题通过。进一步收紧切点指令，并在脚本加入针对该截图问题的具体关系检查，仍结合人工阅读判断。

最终修正版见verified-2.json、verified-3.json。三类对照：

1. 当前截图的多轮累计答案：关系项demonstrated，转入下一点，不再追问旧因果。
2. 保留旧判定的第5轮求助：仍needs_help，先说明C在栈顶／A在队头所以先取出，再引入栈定义，不把收尾算掌握。
3. 无前几轮正确依据、只说LIFO/FIFO：关系项保持未确认，没有无条件放行。

离线测试：17 passed、24 skipped（需要独立测试数据库）。没有把模拟模型测试当作真实文案验证。

## 复跑

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:REPLAY_OUTPUT='student_agent/evidence/stack-dialogue-2026-11-11/recheck.json'
.venv/Scripts/python.exe student_agent/evidence/stack-dialogue-2026-11-11/replay.py
```

固定真实课程与学生输入、小样本单模型，不能推断所有课程均不会重复或突兀切点。历史记录不会自动改写。
