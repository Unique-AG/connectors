import { registerAs } from '@nestjs/config';
import { Redacted } from '../utils/redacted';

export type PermissionsInheritanceMode =
  | 'inherit_scopes_and_files'
  | 'inherit_scopes'
  | 'inherit_files'
  | 'none';

export interface InheritanceSettings {
  inheritScopes: boolean;
  inheritFiles: boolean;
}

export const INHERITANCE_MODES_MAP: Record<PermissionsInheritanceMode, InheritanceSettings> = {
  inherit_scopes_and_files: { inheritScopes: true, inheritFiles: true },
  inherit_scopes: { inheritScopes: true, inheritFiles: false },
  inherit_files: { inheritScopes: false, inheritFiles: true },
  none: { inheritScopes: false, inheritFiles: false },
};

import { getTenantConfig } from './tenant-config-loader';
import { type UniqueConfig, UniqueConfigSchema } from './unique.schema';

export const uniqueConfig = registerAs('unique', (): UniqueConfig => {
  const config = UniqueConfigSchema.parse(getTenantConfig().unique);

  // Inject secrets from environment variables
  if (config.serviceAuthMode === 'external') {
    const secret = process.env.ZITADEL_CLIENT_SECRET;
    if (!secret) {
      throw new Error(
        'ZITADEL_CLIENT_SECRET environment variable is required when using external auth mode',
      );
    }
    return {
      ...config,
      zitadelClientSecret: new Redacted(secret),
    };
  }

  return config;
});

export interface UniqueConfigNamespaced {
  unique: UniqueConfig;
}
