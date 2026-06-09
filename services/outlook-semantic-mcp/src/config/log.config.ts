import { LogsDiagnosticDataPolicy } from '@unique-ag/utils';
import { ConfigType, NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';
import { enabledDisabledBoolean } from '~/utils/zod';

const ConfigSchema = z.object({
  buffering: enabledDisabledBoolean('If the nestjs app should buffer the logs on startup.'),
  diagnosticsDataPolicy: z
    .enum(LogsDiagnosticDataPolicy)
    .prefault(LogsDiagnosticDataPolicy.CONCEAL)
    .describe(
      'Controls whether diagnostic data (names, emails, paths) is smeared or disclosed in logs.',
    ),
});

export const logConfig = registerConfig('log', ConfigSchema);

export type LogConfigNamespaced = NamespacedConfigType<typeof logConfig>;
export type LogConfig = ConfigType<typeof logConfig>;
