/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,

  /* 静态导出：产物是一堆静态文件，由后端 FastAPI 挂载托管，不需要 Node 服务器。
     见 apps/server.py 里的 /app 挂载点。 */
  output: "export",

  /* 挂载在 /app 下，所以 _next/* 这些绝对资源路径也要带上 /app 前缀，
     否则浏览器会去后端根路径找资源，全部 404。 */
  basePath: "/app",

  /* 这个前端现在住在另一个项目里，父目录也有 package-lock.json。
     不指死 root，Turbopack 会往上找到父目录当工作区根，扫描范围跑到项目外。 */
  turbopack: { root: import.meta.dirname },
};

export default nextConfig;
