// Local Windows entry point. Route ownership comes from contracts/routing.yaml
// through local_dev.py; production Caddy configuration is never changed.
import http from 'node:http';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ports = { platform: 8080, teacher: 3200, student: 8001 };

export function routeFor(raw, routes, upstreamPorts = ports) {
  const url = new URL(raw, 'http://localhost:8088');
  for (const route of routes) {
    const matches = route.type === 'fallback' || (route.path.endsWith('*')
      ? url.pathname.startsWith(route.path.slice(0, -1)) : url.pathname === route.path);
    if (!matches) continue;
    if (route.type === 'redirect') {
      return { redirect: route.to.replace('{query}', url.search.slice(1)), code: route.code };
    }
    const targetPath = route.type === 'handle_path'
      ? raw.slice(route.path.slice(0, -2).length) : raw;
    if (!upstreamPorts[route.service]) throw new Error('Unknown local upstream');
    return { port: upstreamPorts[route.service], path: targetPath };
  }
  throw new Error('Missing local fallback route');
}

export function createGateway(routes, upstreamPorts = ports) {
  const headersFor = req => ({ ...req.headers, 'x-forwarded-host': req.headers.host,
    'x-forwarded-proto': 'http', 'x-forwarded-for': req.socket.remoteAddress });
  const server = http.createServer((req, res) => {
    const target = routeFor(req.url, routes, upstreamPorts);
    if (target.redirect !== undefined) {
      res.writeHead(target.code, { location: target.redirect }); res.end(); return;
    }
    const upstream = http.request({ host: '127.0.0.1', port: target.port,
      path: target.path, method: req.method, headers: headersFor(req) }, response => {
      res.writeHead(response.statusCode, response.headers); response.pipe(res);
      response.on('error', () => res.destroy());
    });
    upstream.on('error', () => {
      if (!res.headersSent) res.writeHead(502, { 'content-type': 'text/plain; charset=utf-8' });
      res.end('Local upstream unavailable. See .runtime/local-dev logs.');
    });
    res.on('close', () => upstream.destroy());
    req.on('aborted', () => upstream.destroy()); req.pipe(upstream);
  });
  server.on('upgrade', (req, socket, head) => {
    const target = routeFor(req.url, routes, upstreamPorts);
    if (!target.port) { socket.destroy(); return; }
    const upstream = net.connect(target.port, '127.0.0.1', () => {
      const headers = Object.entries(headersFor(req)).map(([k, v]) => `${k}: ${v}`).join('\r\n');
      upstream.write(`${req.method} ${target.path} HTTP/${req.httpVersion}\r\n${headers}\r\n\r\n`);
      if (head.length) upstream.write(head);
      socket.pipe(upstream); upstream.pipe(socket);
    });
    upstream.on('error', () => socket.destroy()); socket.on('error', () => upstream.destroy());
    socket.on('close', () => upstream.destroy()); upstream.on('close', () => socket.destroy());
  });
  return server;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const routes = JSON.parse(process.env.LOCAL_GATEWAY_ROUTES || 'null');
  if (!Array.isArray(routes)) throw new Error('Start through start-local.ps1 to load the route contract');
  createGateway(routes).listen(8088, '127.0.0.1', () => console.log('Local gateway ready: http://localhost:8088'));
}
