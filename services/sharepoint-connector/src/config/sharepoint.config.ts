import { registerAs } from '@nestjs/config';
import { type SharepointConfig, SharepointConfigSchema } from './sharepoint.schema';
import { getTenantConfig } from './tenant-config-loader';

export const sharepointConfig = registerAs('sharepoint', (): SharepointConfig => {
  const config = SharepointConfigSchema.parse(getTenantConfig().sharepoint);

  // Inject password from environment variable if certificate auth is used and key is encrypted
  if (config.authMode === 'certificate') {
    const password = process.env.SHAREPOINT_AUTH_PRIVATE_KEY_PASSWORD;
    if (password) {
      return {
        ...config,
        authPrivateKeyPassword: password,
      };
    }
  }

  return config;
});

export type { SharepointConfig };
export type SharepointConfigNamespaced = { sharepoint: SharepointConfig };
