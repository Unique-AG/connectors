import { globSync, readFileSync } from 'node:fs';
import { load } from 'js-yaml';
import { TenantConfig, TenantConfigSchema } from './tenant-config.schema';

let cachedConfig: TenantConfig | null = null;

function loadTenantConfig(pathPattern: string): TenantConfig {
  const files = globSync(pathPattern);

  if (files.length === 0) {
    throw new Error(`No tenant configuration files found matching pattern '${pathPattern}'`);
  }

  if (files.length > 1) {
    throw new Error(
      `Multiple tenant configuration files found matching pattern '${pathPattern}': ${files.join(', ')}. Only one tenant config file is supported for now.`,
    );
  }

  const configPath = files[0];
  if (!configPath) {
    throw new Error(`No tenant configuration files found matching pattern '${pathPattern}'`);
  }

  try {
    const fileContent = readFileSync(configPath, 'utf-8');
    const parsedConfig = load(fileContent);

    return TenantConfigSchema.parse(parsedConfig);
  } catch (error) {
    if (error instanceof Error) {
      throw new Error(
        `Failed to load or validate tenant config from ${configPath}: ${error.message}`,
      );
    }
    throw error;
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
