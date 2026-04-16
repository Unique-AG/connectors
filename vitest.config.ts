import swc from 'unplugin-swc';
import type { ViteUserConfig } from 'vitest/config';

export const globalConfig: ViteUserConfig = {
  test: {
    globals: true,
    environment: 'node',
    passWithNoTests: true,
    clearMocks: true,
    reporters: ['verbose'],
  },
  plugins: [
    swc.vite({
      module: { type: 'es6' },
      // SWC defaults to excluding all node_modules. Workspace packages linked
      // via pnpm resolve through node_modules/.pnpm, so SWC skips them too.
      // Without transformation, TypeScript-only syntax (e.g. `import { type X }`)
      // reaches Rollup's JS parser and causes a parse failure.
      exclude: /node_modules\/(?!.*@unique-ag)/,
    }),
  ],
};

export default globalConfig;
