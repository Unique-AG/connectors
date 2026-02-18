import { ZodConfigurableModuleBuilder } from '@proventuslabs/nestjs-zod';
import { Dispatcher } from 'undici';
import { z } from 'zod/v4';
import { UniqueAuthSchema } from './unique-api-auth-schema';

const serviceDefaults = z.object({
  batchSize: z.number().optional().prefault(100),
});

const optionalServiceDefaults = serviceDefaults.prefault({ batchSize: 100 });

export const uniqueApiFeatureModuleOptionsSchema = z.object({
  auth: UniqueAuthSchema,
  dispatcher: z
    .instanceof(Dispatcher)
    .optional()
    .describe(
      `Custom provided dispatcher in case you need to change the default implementation of the dispatcher`,
    ),
  scopeManagment: z.object({
    rateLimitPerMinute: z.number().prefault(1000),
    batchSize: z.number().prefault(100),
    baseUrl: z.string().describe('Base URL for Unique scope management service'),
  }),
  ingestion: z.object({
    rateLimitPerMinute: z.number().prefault(1000),
    batchSize: z.number().prefault(100),
    baseUrl: z.string().describe('Base URL for Unique ingestion service'),
  }),
  users: optionalServiceDefaults,
  groups: optionalServiceDefaults,
  metadata: z
    .object({
      clientName: z.string().optional(),
      tenantKey: z.string().optional(),
    })
    .prefault({}),
});

export type UniqueApiFeatureModuleOptions = z.infer<typeof uniqueApiFeatureModuleOptionsSchema>;

export const uniqueApiFeatureModuleOptionsHost = new ZodConfigurableModuleBuilder(
  uniqueApiFeatureModuleOptionsSchema,
)
  .setClassMethodName('forFeature')
  .build();

export type UniqueApiFeatureModuleInputOptions =
  typeof uniqueApiFeatureModuleOptionsHost.OPTIONS_INPUT_TYPE;
