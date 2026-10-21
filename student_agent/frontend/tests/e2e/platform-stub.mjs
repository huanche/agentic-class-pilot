/* 平台桩（e2e 专用）：替平台响应学生端会拉的两个内部端点。
   - POST /api/v1/internal/student/learning-context → ch3 夹具（6 个知识点）
   - POST /api/v1/internal/student/learning-progress → 尽力而为的 200
   launch_token 验签在学生端本地做（STUDENT_SERVICE_KEY 共享），由测试
   spec 用同 key 签发，本桩不碰令牌。 */
import { createServer } from "node:http";
import { readFileSync } from "node:fs";

const PORT = 8878;
const FIXTURE = new URL("../../../tests/fixtures/platform-learning-context-ch3.json", import.meta.url);
let generatedQuestions = 0;
let endReassessments = 0;

const server = createServer((req, res) => {
  const chunks = [];
  req.on("data", (c) => chunks.push(c));
  req.on("end", () => {
    const json = (body) => res.writeHead(200, { "content-type": "application/json" }).end(body);
    if (req.method === "GET" && req.url === "/mock-llm/metrics") {
      json(JSON.stringify({endReassessments}));
    } else if (req.method === "POST" && req.url === "/mock-llm/chat/completions") {
      const request = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      const system = request.messages[0].content;
      const user = request.messages[1].content;
      let content = "本次能说明关键条件，建议继续练习新的应用情境。";
      if (system.includes("教学评估助手")) endReassessments++;
      if (system.includes("意图分类器")) content = '{"intent":"answer"}';
      else if (system.includes("正在判定学生")) content = JSON.stringify({
        verdict: "correct", performance: user.includes("题目类型：application") ? "transfer" : "understood",
        note: "说明了核心条件及其作用", reasoning: "学生说明了条件变化时应如何调整选择",
      });
      else if (system.includes("要为学生出一个知识检测题")) {
        generatedQuestions++;
        content = user.includes("题目类型：application")
          ? `如果原来的关键条件发生变化，你会怎样应用这个概念并说明理由？（${generatedQuestions}）`
          : `请用自己的话说明核心条件及其作用。（${generatedQuestions}）`;
      }
      json(JSON.stringify({choices: [{message: {content}}]}));
    } else if (req.method === "GET" && req.url === "/healthz") {
      json('{"ok":true}');
    } else if (req.method === "POST" && req.url === "/api/v1/internal/student/learning-context") {
      json(readFileSync(FIXTURE, "utf8"));
    } else if (req.method === "POST" && req.url === "/api/v1/internal/student/learning-progress") {
      json('{"ok":true}');
    } else {
      res.writeHead(404).end("{}");
    }
  });
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`platform stub listening on ${PORT}`);
});
