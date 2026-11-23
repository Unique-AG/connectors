import * as z from 'zod';

const providerStateSchema = z.object({
  sessionId: z.string().min(1),
  sessionNonce: z.string().min(1),
  sessionHmac: z.string().min(1),
});

/** The `state` this server sends to the identity provider, not the MCP client's own state. */
export type ProviderState = z.infer<typeof providerStateSchema>;

export function encodeProviderState(state: ProviderState): string {
  return Buffer.from(JSON.stringify(state)).toString('base64url');
}

export function decodeProviderState(state: string | undefined): ProviderState | undefined {
  if (!state) {
    return undefined;
  }
  try {
    const parsed = providerStateSchema.safeParse(
      JSON.parse(Buffer.from(state, 'base64url').toString('utf-8')),
    );
    return parsed.success ? parsed.data : undefined;
  } catch {
    return undefined;
  }
}
