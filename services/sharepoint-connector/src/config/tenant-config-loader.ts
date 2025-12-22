import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { load } from 'js-yaml';
import { TenantConfig, TenantConfigSchema } from './tenant-config.schema';

let cachedConfig: TenantConfig | null = null;

function loadTenantConfig(tenantConfigDirectory: string): TenantConfig {
  const files = readdirSync(tenantConfigDirectory).filter(
    (file) => file.endsWith('.yaml') || file.endsWith('.yml'),
  );

  if (files.length === 0) {
    throw new Error(`No YAML configuration files found in ${tenantConfigDirectory}`);
  }

  const configFile = files[0];
  if (!configFile) {
    throw new Error(`No YAML configuration files found in ${tenantConfigDirectory}`);
  }

  const configPath = join(tenantConfigDirectory, configFile);

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
    const tenantConfigDirectory = process.env.TENANT_CONFIG_DIRECTORY;
    if (!tenantConfigDirectory) {
      throw new Error('TENANT_CONFIG_DIRECTORY environment variable is not set');
    }
    cachedConfig = loadTenantConfig(tenantConfigDirectory);
  }
  return cachedConfig;
}
