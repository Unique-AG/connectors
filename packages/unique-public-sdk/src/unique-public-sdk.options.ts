import { z } from 'zod/v4';
import type { UserIdentityResolver } from './unique-public-sdk.types';

export const UniquePublicSdkOptionsSchema = z.object({
  /** Base URL for the Unique Public API (e.g., "https://api.unique.app"). */
  apiBaseUrl: z.url(),

  /** API version header value (maps to x-api-version). */
  apiVersion: z.string().default('2023-12-06'),

  /** Extra HTTP headers sent with every API request. */
  serviceHeaders: z.record(z.string(), z.string()),

  /** Optional internal base URL for Azure Blob Storage uploads.
   *  When set, the host portion of writeUrl returned by content/upsert
   *  is replaced with this URL's origin before uploading. */
  storageInternalBaseUrl: z.url().optional(),

  /** Retry configuration for API calls. */
  retry: z
    .object({
      /** Max retry attempts for transient failures. */
      maxAttempts: z.number().int().positive().default(3),
      /** Base delay in ms for exponential backoff. */
      baseDelayMs: z.number().int().positive().default(200),
      /** Max delay cap in ms. */
      maxDelayMs: z.number().int().positive().default(10_000),
    })
    .default({ maxAttempts: 3, baseDelayMs: 200, maxDelayMs: 10_000 }),

  /** Optional user identity resolver for scoped operations. */
  userIdentityResolver: z.custom<UserIdentityResolver>().optional(),
});

export type UniquePublicSdkOptions = z.infer<typeof UniquePublicSdkOptionsSchema>;
export type UniquePublicSdkInputOptions = z.input<typeof UniquePublicSdkOptionsSchema>;
