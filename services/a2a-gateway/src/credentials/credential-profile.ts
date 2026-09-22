import { z } from 'zod';

const secret = z
  .string()
  .min(1)
  .max(16_384)
  .regex(/^[\x20-\x7e]+$/);
const httpsUrl = z.url().refine((value) => {
  const url = new URL(value);
  return url.protocol === 'https:' && !url.username && !url.password && !url.hash && !url.search;
});

export const credentialProfile = z.discriminatedUnion('type', [
  z.object({ type: z.literal('none') }).strict(),
  z.object({ type: z.literal('bearer'), token: secret }).strict(),
  z
    .object({
      type: z.literal('api_key'),
      value: secret,
      header: z
        .string()
        .regex(/^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/)
        .refine(
          (value) =>
            !/^(?:authorization|proxy-.*|host|cookie|set-cookie|content-.*|connection|transfer-encoding|accept|te|trailer|upgrade|forwarded|x-forwarded-.*|x-user-.*|x-company-.*|x-service-id)$/i.test(
              value,
            ),
        ),
    })
    .strict(),
  z
    .object({
      type: z.literal('oauth2_client_credentials'),
      issuer: httpsUrl,
      tokenEndpoint: httpsUrl,
      clientId: secret,
      clientSecret: secret,
      scope: z.string().max(4096).optional(),
      authMethod: z
        .enum(['client_secret_basic', 'client_secret_post'])
        .default('client_secret_basic'),
    })
    .strict(),
]);

export type CredentialProfile = z.infer<typeof credentialProfile>;

export const connectionWrite = z
  .object({
    name: z.string().trim().min(1).max(200),
    agentCardUrl: httpsUrl.refine((value) => !new URL(value).search),
    credential: credentialProfile,
  })
  .strict();
export type ConnectionConfiguration = z.infer<typeof connectionWrite>;
