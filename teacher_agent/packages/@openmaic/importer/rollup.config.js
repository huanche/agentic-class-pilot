import { nodeResolve } from '@rollup/plugin-node-resolve';
import commonjs from '@rollup/plugin-commonjs';
import typescript from '@rollup/plugin-typescript';
import terser from '@rollup/plugin-terser';
import json from '@rollup/plugin-json';
import globals from 'rollup-plugin-node-globals';
import builtins from 'rollup-plugin-node-builtins';

// rollup-plugin-node-globals@1.4.0 injects __dirname/__filename modules by
// concatenating the resolved path into a quoted JavaScript string. Windows
// backslashes are not escaped, so paths such as "\\02-OpenMAIC" fail to parse.
// Keep the upstream plugin behavior, but serialize its generated path value as
// a valid JavaScript string before Rollup parses the virtual module.
const windowsSafeGlobals = () => {
  // Keep the upstream v1.0.1 hardening: the importer does not need Rollup's
  // synthetic __dirname/__filename globals. Disabling them also avoids the
  // Windows path escaping bug handled defensively below.
  const plugin = globals({ dirname: false, filename: false });
  const originalLoad = plugin.load;

  return {
    ...plugin,
    load(id) {
      const result = originalLoad?.call(this, id);
      const prefix = "export default '";
      if (typeof result === 'string' && result.startsWith(prefix) && result.endsWith("'")) {
        return `export default ${JSON.stringify(result.slice(prefix.length, -1))}`;
      }
      return result;
    },
  };
};

const onwarn = (warning) => {
  if (warning.code === 'CIRCULAR_DEPENDENCY') return;
  console.warn(`(!) ${warning.message}`);
};

const plugins = [
  nodeResolve({ browser: true, preferBuiltins: false }),
  commonjs(),
  json(),
  typescript({ tsconfig: './tsconfig.json' }),
  terser(),
  windowsSafeGlobals(),
  builtins(),
];

const createConfig = (output) => ({
  input: 'src/index.ts',
  onwarn,
  output: { ...output, inlineDynamicImports: true },
  plugins,
});

export default [
  createConfig({ file: 'dist/index.umd.js', format: 'umd', name: 'pptxtojsonPro' }),
  createConfig({ file: 'dist/index.cjs', format: 'cjs' }),
  createConfig({ file: 'dist/index.js', format: 'es' }),
];
