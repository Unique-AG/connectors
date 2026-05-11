import { LogsDiagnosticDataPolicy } from '@unique-ag/utils';
import { ConfigType, NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';

const ConfigSchema = z.object({
  diagnosticsDataPolicy: z
    .enum(LogsDiagnosticDataPolicy)
    .prefault(LogsDiagnosticDataPolicy.CONCEAL)
    .describe(
      'Controls whether diagnostic data (names, emails, paths) is smeared or disclosed in logs.',
    ),
});

export const logsConfig = registerConfig('logs', ConfigSchema);

export type LogsConfigNamespaced = NamespacedConfigType<typeof logsConfig>;
export type LogsConfig = ConfigType<typeof logsConfig>;
