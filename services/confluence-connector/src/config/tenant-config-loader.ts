import assert from 'node:assert';
import { globSync, readFileSync } from 'node:fs';
import { registerAs } from '@nestjs/config';
import { load } from 'js-yaml';
import { isPlainObject } from 'remeda';
import { z } from 'zod';
import { AuthMode, type ConfluenceConfig, ConfluenceConfigSchema } from './confluence.schema';
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
      injectSecretsFromEnvironment(config);
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

// TODO: Replace with lite-llm style lazy loading for secrets
// per-tenant env vars is not yet supported and should be addressed when multi-tenant ticket is implemented.
function injectSecretsFromEnvironment(config: Record<string, unknown>): void {
  const confluence = config.confluence as Record<string, unknown> | undefined;
  const confluenceAuth = confluence?.auth as Record<string, unknown> | undefined;
  const unique = config.unique as Record<string, unknown> | undefined;

  if (process.env.CONFLUENCE_CLIENT_SECRET && confluenceAuth?.mode === AuthMode.OAUTH_2LO) {
    confluenceAuth.clientSecret = process.env.CONFLUENCE_CLIENT_SECRET;
  }

  if (process.env.CONFLUENCE_PAT && confluenceAuth?.mode === AuthMode.PAT) {
    confluenceAuth.token = process.env.CONFLUENCE_PAT;
  }

  if (process.env.ZITADEL_CLIENT_SECRET && unique?.serviceAuthMode === 'external') {
    unique.zitadelClientSecret = process.env.ZITADEL_CLIENT_SECRET;
  }
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
