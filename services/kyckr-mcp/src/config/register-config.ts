import type { ConfigObject } from '@nestjs/config';
import { registerConfig as registerNestjsZodConfig } from '@proventuslabs/nestjs-zod';
import type { $ZodType } from 'zod/v4/core';

// nestjs-zod 2.0.1+ types schema input as Record<string, string | undefined>.
// Env values are still decoded at runtime by the original registerConfig.
type EnvRecord = Record<string, string | undefined>;

export function registerConfig<N extends string, C extends ConfigObject>(
  namespace: N,
  configSchema: $ZodType<C>,
  options?: {
    whitelistKeys?: Set<string>;
    variables?: EnvRecord;
    warnOnly?: boolean;
  },
) {
  return registerNestjsZodConfig(
    namespace as Parameters<typeof registerNestjsZodConfig>[0],
    configSchema as $ZodType<C, EnvRecord>,
    options,
  );
}
