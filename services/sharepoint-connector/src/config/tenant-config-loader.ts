import assert from 'node:assert';
import { globSync, readFileSync } from 'node:fs';
import { registerAs } from '@nestjs/config';
import { load } from 'js-yaml';
import { isPlainObject } from 'remeda';
import { Redacted } from 'src/utils/redacted';
import { z } from 'zod';
import { type ProcessingConfig, ProcessingConfigSchema } from './processing.schema';
import { type SharepointConfig, SharepointConfigSchema } from './sharepoint.schema';
import { type UniqueConfig, UniqueConfigSchema } from './unique.schema';

export { type AppConfig, type AppConfigNamespaced, appConfig } from './app.config';
export type { ProcessingConfig } from './processing.schema';
export type { SharepointConfig } from './sharepoint.schema';
export type { UniqueConfig } from './unique.schema';

// ==========================================
// Tenant Configuration
// ==========================================

const TenantConfigSchema = z.object({
  sharepoint: SharepointConfigSchema,
  unique: UniqueConfigSchema,
  processing: ProcessingConfigSchema,
});

type TenantConfig = z.infer<typeof TenantConfigSchema>;

// --- Tenant Configs (From File) ---

/**
 * Helper to register configurations that are extracted and validated from the tenant YAML file.
 */
const fromTenant = <T extends z.ZodTypeAny>(key: keyof TenantConfig, schema: T) =>
  registerAs(key as string, () => schema.parse(getTenantConfig()[key]) as Record<string, unknown>);

export const sharepointConfig = fromTenant('sharepoint', SharepointConfigSchema);
export const uniqueConfig = fromTenant('unique', UniqueConfigSchema);
export const processingConfig = fromTenant('processing', ProcessingConfigSchema);

export interface SharepointConfigNamespaced {
  sharepoint: SharepointConfig;
}
export interface UniqueConfigNamespaced {
  unique: UniqueConfig;
}
export interface ProcessingConfigNamespaced {
  processing: ProcessingConfig;
}

let cachedConfig: TenantConfig | null = null;

function loadTenantConfig(pathPattern: string): TenantConfig {
  const files = globSync(pathPattern);

  // We do not support multiple tenants for now: UN-13091
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
  // Type assertion for discriminated union
  const typedConfig = config as TenantConfig;

  // we throw an error if the object path is not defined
  if (
    process.env.SHAREPOINT_AUTH_PRIVATE_KEY_PASSWORD &&
    typedConfig.sharepoint.auth.mode === 'certificate'
  ) {
    typedConfig.sharepoint.auth.privateKeyPassword =
      process.env.SHAREPOINT_AUTH_PRIVATE_KEY_PASSWORD;
  }

  if (process.env.ZITADEL_CLIENT_SECRET && typedConfig.unique.serviceAuthMode === 'external') {
    typedConfig.unique.zitadelClientSecret = new Redacted(process.env.ZITADEL_CLIENT_SECRET);
  }
}

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
