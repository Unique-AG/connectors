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
  plugins: [swc.vite({ module: { type: 'es6' } })],
};

export default globalConfig;
