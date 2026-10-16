import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
const here = path.dirname(fileURLToPath(import.meta.url));
const teacher = path.resolve(here, '../..');
const require = createRequire(path.join(teacher, 'package.json'));
const { build } = createRequire(require.resolve('tsx/package.json'))('esbuild');
const packageRoot = path.join(teacher, 'packages/@openmaic/generation');
const embedded = {};
for (const folder of ['templates', 'snippets']) {
  for (const file of await fs.readdir(path.join(packageRoot, folder), { recursive: true })) {
    if (!file.endsWith('.md')) continue;
    embedded[`/embedded-prompts/${folder}/${file.replaceAll('\\', '/')}`] = await fs.readFile(
      path.join(packageRoot, folder, file),
      'utf8',
    );
  }
}
const output = process.argv[2];
if (!output) throw new Error('Usage: node build-smoke.mjs <output.mjs>');
await build({
  entryPoints: [path.join(here, 'smoke.ts')],
  outfile: path.resolve(output),
  bundle: true,
  platform: 'node',
  format: 'esm',
  target: 'node22',
  alias: {
    '@': teacher,
    '@openmaic/generation': path.join(packageRoot, 'src/index.ts'),
    '@openmaic/dsl': path.join(teacher, 'packages/@openmaic/dsl/src/index.ts'),
  },
  banner: {
    js: "import { createRequire as __createRequire } from 'node:module'; const require = __createRequire(import.meta.url);",
  },
  plugins: [
    {
      name: 'embed-package-prompts',
      setup(builder) {
        builder.onLoad(
          { filter: /[\\/]generation[\\/]src[\\/]prompts[\\/]loader\.ts$/ },
          async ({ path: filename }) => {
            let contents = await fs.readFile(filename, 'utf8');
            contents = contents.replace(
              "import { readFileSync } from 'node:fs';",
              `const __prompts = ${JSON.stringify(embedded)}; function readFileSync(filename: string, _encoding: string) { const key = filename.replaceAll('\\\\', '/'); if (key in __prompts) return __prompts[key as keyof typeof __prompts]; throw Object.assign(new Error('Missing embedded prompt'), {code:'ENOENT'}); }`,
            );
            contents = contents.replace(
              "const DEFAULT_PROMPTS_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '../..');",
              "const DEFAULT_PROMPTS_DIR = '/embedded-prompts';",
            );
            return { contents, loader: 'ts', resolveDir: path.dirname(filename) };
          },
        );
      },
    },
  ],
  logLevel: 'warning',
});
console.log('Built isolated live-model smoke bundle with repository prompt assets.');
