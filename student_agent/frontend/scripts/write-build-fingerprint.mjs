/* 构建指纹:把「这份产物是从哪份源码构建出来的」写进 out/.build-fingerprint。
 *
 * 背景(2026-10-09 排查):server.py 在 apps/static/app 为空时回退 serve
 * frontend/out/——改了 frontend/src 忘记重新构建时,浏览器一直拿到旧行为,
 * 全程没有任何报错。启动时的守卫(apps/server.py 的 _frontend_fingerprint)
 * 重算同一份哈希并比对,对不上就大声警告。
 *
 * 输入 = frontend/src/** 全部文件 + 三个构建配置,按 posix 相对路径排序后
 * 逐个喂给 sha256(相对路径 + \0 + 文件内容的 sha256 摘要)。
 * ⚠️ 算法和文件清单必须与 apps/server.py 的 _frontend_fingerprint 保持
 * 一致,两边任一处改动都要同步另一边。
 */
import { createHash } from "node:crypto";
import { readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join, relative, sep } from "node:path";

const frontendRoot = fileURLToPath(new URL("..", import.meta.url));
const outDir = join(frontendRoot, "out");
const srcDir = join(frontendRoot, "src");

function walk(dir) {
  const files = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) files.push(...walk(full));
    else files.push(full);
  }
  return files;
}

const inputs = [];
for (const name of ["package.json", "package-lock.json", "next.config.mjs"]) {
  const path = join(frontendRoot, name);
  try {
    inputs.push([name, readFileSync(path)]);
  } catch {
    /* 该配置不存在就跳过——python 侧同样处理 */
  }
}
for (const path of walk(srcDir)) {
  const rel = relative(frontendRoot, path).split(sep).join("/");
  inputs.push([rel, readFileSync(path)]);
}

const combined = createHash("sha256");
for (const [rel, blob] of inputs.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))) {
  combined.update(rel, "utf8");
  combined.update("\0");
  combined.update(createHash("sha256").update(blob).digest());
}

const hex = combined.digest("hex"); // digest() 只能取一次，取第二次会抛 ERR_CRYPTO_HASH_FINALIZED
writeFileSync(join(outDir, ".build-fingerprint"), hex + "\n");
console.log(`build fingerprint written: ${hex.slice(0, 16)}… (${inputs.length} files)`);
