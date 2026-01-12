import { globSync, readFileSync } from 'node:fs';
import { registerAs } from '@nestjs/config';
import { ConfigType, NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { load } from 'js-yaml';
import { z } from 'zod';
import { Redacted } from '../utils/redacted';
import {
  AppConfigSchema,
  ProcessingConfigSchema,
  SharepointConfigSchema,
  TenantConfigSchema,
  UniqueConfigSchema,
} from './tenant-config.schema';

type TenantConfig = z.infer<typeof TenantConfigSchema>;
type SharepointConfig = z.infer<typeof SharepointConfigSchema>;
type UniqueConfig = z.infer<typeof UniqueConfigSchema>;
type ProcessingConfig = z.infer<typeof ProcessingConfigSchema>;

// --- App Config (From Environment) ---

export const appConfig = registerConfig('app', AppConfigSchema, {
  whitelistKeys: new Set([
    'LOG_LEVEL',
    'PORT',
    'NODE_ENV',
    'LOGS_DIAGNOSTICS_DATA_POLICY',
    'TENANT_CONFIG_PATH_PATTERN',
  ]),
});

export type AppConfig = ConfigType<typeof appConfig>;
export type AppConfigNamespaced = NamespacedConfigType<typeof appConfig>;

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

// Intermediate schema for environment variable injection before final validation
const IntermediateTenantSchema = z
  .object({
    sharepoint: z
      .object({
        auth: z
          .object({
            mode: z.enum(['oidc', 'client-secret', 'certificate']).optional(),
            privateKeyPassword: z.string().optional(),
          })
          .optional(),
      })
      .optional(),
    unique: z
      .object({
        serviceAuthMode: z.enum(['cluster_local', 'external']).optional(),
        zitadelClientSecret: z.instanceof(Redacted).optional(),
      })
      .optional(),
  })
  .passthrough();

function loadTenantConfig(pathPattern: string): TenantConfig {
  const files = globSync(pathPattern);

  if (files.length === 0) {
    throw new Error(`No tenant configuration files found matching pattern '${pathPattern}'`);
  }

  // We do not support multiple tenants for now: UN-13091
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
    const rawConfig = load(fileContent);

    const initialConfig = IntermediateTenantSchema.parse(rawConfig);

    if (initialConfig.sharepoint?.auth?.mode === 'certificate') {
      const password = process.env.SHAREPOINT_AUTH_PRIVATE_KEY_PASSWORD;
      if (password) {
        initialConfig.sharepoint.auth.privateKeyPassword = password;
      }
    }

    if (initialConfig.unique?.serviceAuthMode === 'external') {
      const secret = process.env.ZITADEL_CLIENT_SECRET;
      if (!secret) {
        throw new Error(
          `ZITADEL_CLIENT_SECRET environment variable is required when using external auth mode (configured in ${configPath})`,
        );
      }
      initialConfig.unique.zitadelClientSecret = new Redacted(secret);
    }

    return TenantConfigSchema.parse(initialConfig);
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
