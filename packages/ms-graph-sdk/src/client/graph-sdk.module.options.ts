import { ZodConfigurableModuleBuilder } from '@proventuslabs/nestjs-zod';
import z from 'zod/v4';

const schema = z.object({
  getToken: z.custom<(userProfileId: string) => Promise<string>>(
    (val) => typeof val === 'function',
    { message: 'getToken must be a function' },
  ),
  apiVersion: z.enum(['v1.0', 'beta']).default('v1.0'),
  defaultHeaders: z.record(z.string(), z.string()).optional(),
  retry: z
    .object({
      maxAttempts: z.number().int().min(1),
      maxServerDelay: z.number().int().min(0),
    })
    .default({ maxAttempts: 3, maxServerDelay: 30_000 }),
});

export const { ConfigurableModuleClass, MODULE_OPTIONS_TOKEN, OPTIONS_TYPE, OPTIONS_INPUT_TYPE } =
  new ZodConfigurableModuleBuilder(schema).setClassMethodName('register').build();
