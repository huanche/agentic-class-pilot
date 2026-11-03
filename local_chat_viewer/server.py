"""Local-only proxy for the teacher conversation viewer.

Run: python local_chat_viewer/server.py
Open: http://127.0.0.1:8765/
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

HOST, PORT = "127.0.0.1", 8765
PAGE = Path(__file__).with_name("index.html")
state = {"origin": None, "token": None}
API_PREFIX = "/api/v1/teacher-chat-records"


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, content, mime="application/json; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/":
            self.reply(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            return
        if not path.startswith(API_PREFIX + "/") or path == API_PREFIX + "/login":
            self.reply(404, b'{"detail":"Not found"}')
            return
        if not state["token"]:
            self.reply(401, b'{"detail":"Please log in"}')
            return
        upstream = state["origin"] + self.path
        request = Request(upstream, headers={"Authorization": "Bearer " + state["token"]})
        try:
            with urlopen(request, timeout=20) as response:
                self.reply(response.status, response.read())
        except HTTPError as error:
            self.reply(error.code, error.read())
        except URLError:
            self.reply(502, b'{"detail":"Cannot reach the platform server"}')

    def do_POST(self):
        path = urlsplit(self.path).path
        if path == API_PREFIX + "/logout":
            state.update(origin=None, token=None)
            self.reply(200, b'{}')
            return
        if path != API_PREFIX + "/login":
            self.reply(404, b'{"detail":"Not found"}')
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 8192:
                raise ValueError("Request too large")
            body = json.loads(self.rfile.read(length))
            origin = str(body["origin"]).rstrip("/")
            parsed = urlsplit(origin)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path:
                raise ValueError("请输入平台的 HTTPS 网址，例如 https://example.com")
            form = urlencode({"username": body["username"], "password": body["password"]}).encode()
            request = Request(origin + "/api/v1/login/access-token", data=form,
                              headers={"Content-Type": "application/x-www-form-urlencoded"})
            with urlopen(request, timeout=20) as response:
                token = json.load(response)["access_token"]
            # Verify the account has permission for the viewer before retaining the token.
            request = Request(origin + API_PREFIX + "/courses",
                              headers={"Authorization": "Bearer " + token})
            with urlopen(request, timeout=20) as response:
                response.read()
            state.update(origin=origin, token=token)
            self.reply(200, b'{}')
        except (ValueError, KeyError, json.JSONDecodeError) as error:
            self.reply(400, json.dumps({"detail": str(error)}, ensure_ascii=False).encode())
        except HTTPError as error:
            detail = "教师登录失败" if error.code in (400, 401) else (
                "服务器尚未部署聊天读取接口，或账号没有教师权限" if error.code in (403, 404)
                else f"服务器返回 HTTP {error.code}")
            self.reply(error.code, json.dumps({"detail": detail}, ensure_ascii=False).encode())
        except URLError:
            self.reply(502, json.dumps({"detail": "无法连接该平台网址"}, ensure_ascii=False).encode())


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"聊天记录面板: http://{HOST}:{PORT}/")
    server.serve_forever()
