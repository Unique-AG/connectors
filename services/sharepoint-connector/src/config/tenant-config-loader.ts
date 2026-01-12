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

// Derive types from schemas instead of importing them
type ProcessingConfig = z.infer<typeof ProcessingConfigSchema>;
type SharepointConfig = z.infer<typeof SharepointConfigSchema>;
type TenantConfig = z.infer<typeof TenantConfigSchema>;
type UniqueConfig = z.infer<typeof UniqueConfigSchema>;

export const appConfig = registerConfig('app', AppConfigSchema, {
  whitelistKeys: new Set([
    'LOG_LEVEL',
    'PORT',
    'NODE_ENV',
    'LOGS_DIAGNOSTICS_DATA_POLICY',
    'TENANT_CONFIG_PATH_PATTERN',
  ]),
});

export type AppConfigNamespaced = NamespacedConfigType<typeof appConfig>;
export type AppConfig = ConfigType<typeof appConfig>;

export const sharepointConfig = registerAs('sharepoint', (): SharepointConfig => {
  return SharepointConfigSchema.parse(getTenantConfig().sharepoint);
});

export interface SharepointConfigNamespaced {
  sharepoint: SharepointConfig;
}

export const uniqueConfig = registerAs('unique', (): UniqueConfig => {
  return UniqueConfigSchema.parse(getTenantConfig().unique);
});

export interface UniqueConfigNamespaced {
  unique: UniqueConfig;
}

export const processingConfig = registerAs('processing', (): ProcessingConfig => {
  return ProcessingConfigSchema.parse(getTenantConfig().processing);
});

export interface ProcessingConfigNamespaced {
  processing: ProcessingConfig;
}

let cachedConfig: TenantConfig | null = null;

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
    const parsedConfig = load(fileContent) as Record<string, unknown>;

    // Type for intermediate manipulation before Zod validation
    const raw = parsedConfig as {
      sharepoint?: {
        auth?: {
          mode?: string;
          privateKeyPassword?: string;
        };
      };
      unique?: {
        serviceAuthMode?: string;
        zitadelClientSecret?: Redacted<string>;
      };
    };

    if (raw.sharepoint?.auth?.mode === 'certificate') {
      const password = process.env.SHAREPOINT_AUTH_PRIVATE_KEY_PASSWORD;
      if (password) {
        raw.sharepoint.auth.privateKeyPassword = password;
      }
    }

    if (raw.unique?.serviceAuthMode === 'external') {
      const secret = process.env.ZITADEL_CLIENT_SECRET;
      if (!secret) {
        throw new Error(
          'ZITADEL_CLIENT_SECRET environment variable is required when using external auth mode',
        );
      }
      raw.unique.zitadelClientSecret = new Redacted(secret);
    }

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
