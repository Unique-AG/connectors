import assert from 'node:assert';
import { globSync, readFileSync } from 'node:fs';
import { registerAs } from '@nestjs/config';
import { load } from 'js-yaml';
import { isPlainObject } from 'remeda';
import { z } from 'zod';
import { type ConfluenceConfig, ConfluenceConfigSchema } from './confluence.schema';
import { type ProcessingConfig, ProcessingConfigSchema } from './processing.schema';
import { type UniqueConfig, UniqueConfigSchema } from './unique.schema';

export { type AppConfig, type AppConfigNamespaced, appConfig } from './app.config';
export type { ConfluenceConfig } from './confluence.schema';
export type { ProcessingConfig } from './processing.schema';
export type { UniqueConfig } from './unique.schema';

let cachedConfig: TenantConfig | null = null;
export function getTenantConfig(): TenantConfig {
  if (!cachedConfig) {
    const tenantConfigPathPattern = process.env.TENANT_CONFIG_PATH_PATTERN;
    if (!tenantConfigPathPattern) {
      throw new Error('TENANT_CONFIG_PATH_PATTERN environment variable is not set');
    }
    cachedConfig = loadTenantConfig(tenantConfigPathPattern);
  }
  return cachedConfig;
}

function loadTenantConfig(pathPattern: string): TenantConfig {
  const files = globSync(pathPattern);
  assert.ok(
    files.length < 2,
    `Multiple tenant configuration files found matching pattern '${pathPattern}': ${files.join(', ')}. Only one tenant config file is supported for now.`,
  );
  const configPath =
    files[0] ??
    assert.fail(`No tenant configuration files found matching pattern '${pathPattern}'`);
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
}

function injectSecretsFromEnvironment(config: Record<string, unknown>): void {
  const typedConfig = config as {
    confluence: { auth: { mode: string; apiToken?: string; token?: string; password?: string } };
    unique: { serviceAuthMode: string; zitadelClientSecret?: string };
  };

  if (process.env.CONFLUENCE_API_TOKEN && typedConfig.confluence.auth.mode === 'api_token') {
    typedConfig.confluence.auth.apiToken = process.env.CONFLUENCE_API_TOKEN;
  }

  if (process.env.CONFLUENCE_PAT && typedConfig.confluence.auth.mode === 'pat') {
    typedConfig.confluence.auth.token = process.env.CONFLUENCE_PAT;
  }

  if (process.env.CONFLUENCE_PASSWORD && typedConfig.confluence.auth.mode === 'basic') {
    typedConfig.confluence.auth.password = process.env.CONFLUENCE_PASSWORD;
  }

  if (process.env.ZITADEL_CLIENT_SECRET && typedConfig.unique.serviceAuthMode === 'external') {
    typedConfig.unique.zitadelClientSecret = process.env.ZITADEL_CLIENT_SECRET;
  }
}

const TenantConfigSchema = z.object({
  confluence: ConfluenceConfigSchema,
  unique: UniqueConfigSchema,
  processing: ProcessingConfigSchema,
});
type TenantConfig = z.infer<typeof TenantConfigSchema>;

export const confluenceConfig = registerAs('confluence', () => getTenantConfig().confluence);
export const uniqueConfig = registerAs('unique', () => getTenantConfig().unique);
export const processingConfig = registerAs('processing', () => getTenantConfig().processing);

export interface ConfluenceConfigNamespaced {
  confluence: ConfluenceConfig;
}
export interface UniqueConfigNamespaced {
  unique: UniqueConfig;
}
export interface ProcessingConfigNamespaced {
  processing: ProcessingConfig;
}
