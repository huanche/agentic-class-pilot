import { version } from '../../packages/@openmaic/importer/package.json';

/** Runtime modules are cached by URL; an importer release must get a fresh module identity. */
export const PPTX_IMPORTER_URL = `/vendor/maic-importer/index.js?v=${version}`;
