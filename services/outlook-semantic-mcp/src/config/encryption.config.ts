import {
  type ConfigType,
  type NamespacedConfigType,
  registerConfig,
} from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';
import { redacted } from '~/utils/zod';

const ConfigSchema = z.object({
  key: redacted(
    z
      .instanceof(Buffer)
      .or(z.hex().transform((key) => Buffer.from(key, 'hex')))
      .or(z.base64().transform((key) => Buffer.from(key, 'base64')))
      .refine(
        (buffer) => buffer.length === 32,
        "Key must be 32 bytes (AES-256). Ensure its generated in a suitable way like 'openssl rand -hex 32' or terraform 'random_id'.",
      ),
  ).describe(
    'The secret key for the MCP Server to encrypt and decrypt stored data. Needs to be a 32-byte (256-bit) secret.',
  ),
});

export const encryptionConfig = registerConfig('encryption', ConfigSchema);

export type EncryptionConfigNamespaced = NamespacedConfigType<typeof encryptionConfig>;
export type EncryptionConfig = ConfigType<typeof encryptionConfig>;
