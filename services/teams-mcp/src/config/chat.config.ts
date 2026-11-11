import {
  type ConfigType,
  type NamespacedConfigType,
  registerConfig,
} from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';

const ChatConfigSchema = z.object({
  integration: z
    .enum(['enabled', 'disabled'])
    .default('enabled')
    .describe(
      'Chat integration toggle (independent of UNIQUE_INTEGRATION). When enabled, the ' +
        'Teams chat/channel messaging tools are registered and the messaging Graph scopes ' +
        'are requested. Defaults to enabled for backward compatibility.',
    ),
});

export const chatConfig = registerConfig('chat', ChatConfigSchema);

export type ChatConfigNamespaced = NamespacedConfigType<typeof chatConfig>;
export type ChatConfig = ConfigType<typeof chatConfig>;
