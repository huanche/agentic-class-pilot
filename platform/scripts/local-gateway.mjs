import http from 'node:http';
import net from 'node:net';
const teacherPages = /^\/(?:_next|avatars|teacher-workspace|course-space|classroom-player|classes|classroom|prepare|review|generation-preview|settings|logo-horizontal\.png)(?:\/|\?|$)/;
function target(raw) {
  const path = new URL(raw, 'http://localhost').pathname;
  if (path.startsWith('/teacher/')) return {port:3200,path:raw.slice(8)};
  if (path === '/app' || path.startsWith('/app/') || path.startsWith('/api/session/')) return {port:8000,path:raw};
  if (path.startsWith('/api/v1/')) return {port:8080,path:raw};
  if (path.startsWith('/api/') || teacherPages.test(path)) return {port:3200,path:raw};
  return {port:8080,path:raw};
}
const server=http.createServer((req,res)=>{
  if (req.url === '/teacher') {res.writeHead(302,{location:'/'});res.end();return;}
  if (req.url.startsWith('/student-agent/app')) {res.writeHead(302,{location:req.url.replace('/student-agent/app','/app')});res.end();return;}
  if (['/brand-mark.png','/mentra-icon.svg','/mentra-logo.svg','/favicon.ico','/icon.svg','/apple-icon.png'].includes(req.url)) {res.writeHead(302,{location:'/app/brand-mark.png'});res.end();return;}
  const dest=target(req.url);
  const headers={...req.headers,'x-forwarded-host':req.headers.host,'x-forwarded-proto':'http','x-forwarded-for':req.socket.remoteAddress};
  const upstream=http.request({host:'127.0.0.1',port:dest.port,path:dest.path,method:req.method,headers}, response=>{
    res.writeHead(response.statusCode,response.headers);response.pipe(res);
  });
  upstream.on('error',()=>{if(!res.headersSent)res.writeHead(502,{'content-type':'text/plain; charset=utf-8'});res.end('本地服务正在启动或暂不可用，请稍后刷新。');});
  req.on('aborted',()=>upstream.destroy()); req.pipe(upstream);
});
server.on('upgrade',(req,socket,head)=>{
  const dest=target(req.url); const upstream=net.connect(dest.port,'127.0.0.1',()=>{
    const headers=Object.entries(req.headers).map(([k,v])=>`${k}: ${v}`).join('\r\n');
    upstream.write(`${req.method} ${dest.path} HTTP/${req.httpVersion}\r\n${headers}\r\n\r\n`);
    if(head.length)upstream.write(head);socket.pipe(upstream);upstream.pipe(socket);
  });
  upstream.on('error',()=>socket.destroy());socket.on('error',()=>upstream.destroy());
});
server.listen(8088,'127.0.0.1',()=>console.log('Local gateway ready http://localhost:8088'));
