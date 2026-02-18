import { ZodConfigurableModuleBuilder } from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';

const uniqueApiRootModuleOptionsSchema = z.object({
  observability: z
    .object({
      loggerContext: z
        .string()
        .optional()
        .prefault(`UniqueApi`)
        .describe(`The logger context which will be present in package logs`),
      metricPrefix: z
        .string()
        .optional()
        .prefault(`unique_api`)
        .describe(`The metrics prefix which will be present in all the metrics`),
    })
    .optional()
    .prefault({
      loggerContext: `UniqueApi`,
      metricPrefix: `unique_api`,
    }),
});

export type UniqueApiRootModuleOptions = z.infer<typeof uniqueApiRootModuleOptionsSchema>;

export const uniqueApiRootModuleHost = new ZodConfigurableModuleBuilder(
  uniqueApiRootModuleOptionsSchema,
)
  .setClassMethodName('forRoot')
  .build();

export type UniqueApiRootModuleInputOptions = typeof uniqueApiRootModuleHost.OPTIONS_INPUT_TYPE;
