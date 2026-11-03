import { createClient } from '@hey-api/openapi-ts';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const expected = JSON.parse(readFileSync(path.join(root, 'package.json'))).devDependencies['@hey-api/openapi-ts'];
const actual = JSON.parse(readFileSync(path.join(root, 'node_modules/@hey-api/openapi-ts/package.json'))).version;
if (actual !== expected) throw new Error(`Generator version mismatch: expected ${expected}, got ${actual}`);
const [input, output] = process.argv.slice(2);
if (!input || !output) throw new Error('Usage: node generate-typescript.mjs <bundled-input> <temporary-output>');
await createClient({
  input,
  output: { path: output, clean: true, postProcess: [], tsConfigPath: path.join(root, 'tsconfig.json') },
  plugins: ['@hey-api/typescript', '@hey-api/sdk', '@hey-api/client-fetch'],
});
