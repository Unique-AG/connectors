import assert from 'node:assert';
import { globSync, readFileSync } from 'node:fs';
import { registerAs } from '@nestjs/config';
import { load } from 'js-yaml';
import { isPlainObject } from 'remeda';
import { z } from 'zod';
import { type ConfluenceConfig, ConfluenceConfigSchema } from './confluence.schema';
import { type ProcessingConfig, ProcessingConfigSchema } from './processing.schema';
import { type UniqueConfig, UniqueConfigSchema } from './unique.schema';

const TenantConfigSchema = z.object({
  confluence: ConfluenceConfigSchema,
  unique: UniqueConfigSchema,
  processing: ProcessingConfigSchema,
});
export type TenantConfig = z.infer<typeof TenantConfigSchema>;

let cachedConfigs: TenantConfig[] | null = null;
export function getTenantConfigs(): TenantConfig[] {
  if (!cachedConfigs) {
    const tenantConfigPathPattern = process.env.TENANT_CONFIG_PATH_PATTERN;
    assert.ok(
      tenantConfigPathPattern,
      'TENANT_CONFIG_PATH_PATTERN environment variable is not set',
    );
    cachedConfigs = loadTenantConfigs(tenantConfigPathPattern);
  }
  return cachedConfigs;
}

function loadTenantConfigs(pathPattern: string): TenantConfig[] {
  const files = globSync(pathPattern);
  assert.ok(
    files.length > 0,
    `No tenant configuration files found matching pattern '${pathPattern}'`,
  );

  return files.map((configPath) => {
    try {
      const fileContent = readFileSync(configPath, 'utf-8');
      const config = load(fileContent);
      assert.ok(
        isPlainObject(config),
        `Invalid tenant config: expected a plain object, got ${typeof config}`,
      );
      return TenantConfigSchema.parse(config);
    } catch (error) {
      if (error instanceof Error) {
        throw new Error(
          `Failed to load or validate tenant config from ${configPath}: ${error.message}`,
        );
      }
      throw error;
    }
  });
}

// Full multi-tenant support is not yet implemented, so we return the first tenant config for now
function getFirstTenantConfig(): TenantConfig {
  const configs = getTenantConfigs();
  const first = configs[0];
  assert.ok(first, 'No tenant configurations loaded');
  return first;
}

export const confluenceConfig = registerAs('confluence', () => getFirstTenantConfig().confluence);
export const uniqueConfig = registerAs('unique', () => getFirstTenantConfig().unique);
export const processingConfig = registerAs('processing', () => getFirstTenantConfig().processing);

export interface ConfluenceConfigNamespaced {
  confluence: ConfluenceConfig;
}
export interface UniqueConfigNamespaced {
  unique: UniqueConfig;
}
export interface ProcessingConfigNamespaced {
  processing: ProcessingConfig;
}
