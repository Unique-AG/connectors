// pino-http auto-wraps custom `req` serializers, so the function receives the
// output of `pino-std-serializers.reqSerializer`, not a raw IncomingMessage.
type SerializedReq = { url?: string } & Record<string, unknown>;

export function createRedactRequestSerializer(apiKey: string) {
  return (req: SerializedReq) => {
    if (apiKey && typeof req.url === 'string') {
      return { ...req, url: req.url.replaceAll(apiKey, '[Redacted]') };
    }
    return req;
  };
}
