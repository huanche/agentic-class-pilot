/* 平台桩（e2e 专用）：替平台响应学生端会拉的两个内部端点。
   - POST /api/v1/internal/student/learning-context → ch3 夹具（6 个知识点）
   - POST /api/v1/internal/student/learning-progress → 尽力而为的 200
   launch_token 验签在学生端本地做（STUDENT_SERVICE_KEY 共享），由测试
   spec 用同 key 签发，本桩不碰令牌。 */
import { createServer } from "node:http";
import { readFileSync } from "node:fs";

const PORT = 8878;
const FIXTURE = new URL("../../../tests/fixtures/platform-learning-context-ch3.json", import.meta.url);

const server = createServer((req, res) => {
  const chunks = [];
  req.on("data", (c) => chunks.push(c));
  req.on("end", () => {
    const json = (body) => res.writeHead(200, { "content-type": "application/json" }).end(body);
    if (req.method === "GET" && req.url === "/healthz") {
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
