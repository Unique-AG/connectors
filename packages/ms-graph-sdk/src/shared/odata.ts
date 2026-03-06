import z from 'zod/v4';

export const ODataCollection = <S extends z.core.$ZodType>(itemSchema: S) =>
  z.object({
    '@odata.context': z.string().optional(),
    '@odata.count': z.number().optional(),
    '@odata.nextLink': z.string().optional(),
    value: z.array(itemSchema),
  });

export const ODataDeltaCollection = <S extends z.core.$ZodType>(itemSchema: S) =>
  ODataCollection(itemSchema).extend({
    '@odata.deltaLink': z.string().optional(),
  });

export const BatchRequestPayload = z.object({
  id: z.string(),
  method: z.enum(['GET', 'POST', 'PATCH', 'DELETE']),
  url: z.string(),
  headers: z.record(z.string(), z.string()).optional(),
  body: z.unknown().optional(),
});

export const BatchResponsePayload = z.object({
  id: z.string(),
  status: z.number(),
  headers: z.record(z.string(), z.string()).optional(),
  body: z.unknown().nullish(),
});

export const BatchRequest = z.object({ requests: z.array(BatchRequestPayload) });
export const BatchResponse = z.object({ responses: z.array(BatchResponsePayload) });

export type BatchRequestPayload = z.infer<typeof BatchRequestPayload>;
export type BatchResponsePayload = z.infer<typeof BatchResponsePayload>;

// Each field carries a transform that serialises it to a URL param string.
// z.input<> gives the natural call-site type; z.output<> is all-strings for buildUrl.
export const ODataQueryParamsSchema = z.object({
  $select: z
    .array(z.string())
    .transform((v) => v.join(','))
    .optional(),
  $filter: z.string().optional(),
  $expand: z.string().optional(),
  $top: z.number().int().positive().transform(String).optional(),
  $skip: z.number().int().nonnegative().transform(String).optional(),
  $orderby: z.string().optional(),
  $count: z
    .literal(true)
    .transform(() => 'true')
    .optional(),
  $search: z.string().optional(),
});

export type ODataQueryParams = z.input<typeof ODataQueryParamsSchema>;

export function buildUrl(path: string, params?: ODataQueryParams): string {
  if (!params) return path;
  const serialized = ODataQueryParamsSchema.parse(params);
  const entries = Object.entries(serialized).filter(
    (e): e is [string, string] => e[1] !== undefined,
  );
  if (!entries.length) return path;
  const qs = entries.map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&');
  return `${path}?${qs}`;
}
