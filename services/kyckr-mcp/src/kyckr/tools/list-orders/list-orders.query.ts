import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { KyckrApiError, KyckrHttpClient } from '../../kyckr-http.client';
import {
  KyckrBaseResponseShape,
  KyckrOrdersPageSchema,
  McpEnvelopeShape,
} from '../../schemas/kyckr.schemas';

export const ListOrdersInputSchema = z.object({
  startDate: z
    .string()
    .trim()
    .min(1)
    .optional()
    .describe(
      'Earliest order date to include, ISO 8601 (`YYYY-MM-DD` or full timestamp). Forwarded to Kyckr verbatim.',
    ),
  endDate: z
    .string()
    .trim()
    .min(1)
    .optional()
    .describe(
      'Latest order date to include, ISO 8601 (`YYYY-MM-DD` or full timestamp). Forwarded to Kyckr verbatim.',
    ),
  isoCode: z
    .string()
    .trim()
    .toUpperCase()
    .regex(/^[A-Z]{2}$/, 'Must be a 2-letter ISO 3166 alpha-2 code, e.g. GB, IE, AU.')
    .optional()
    .describe('Restrict to orders against a specific jurisdiction, e.g. GB or AU.'),
});

export type ListOrdersInput = z.infer<typeof ListOrdersInputSchema>;

const ListOrdersEnvelopeSchema = z
  .object({
    ...KyckrBaseResponseShape,
    data: KyckrOrdersPageSchema.optional(),
  })
  .loose();

export const ListOrdersOutputSchema = z
  .object({
    ...McpEnvelopeShape,
    data: KyckrOrdersPageSchema.optional().describe(
      'Paginated orders page. The orders themselves are at `data.orders`. Pagination is at `data.pageNumber` / `data.pageSize` / `data.totalCount`.',
    ),
  })
  .loose();

export type ListOrdersResult = z.infer<typeof ListOrdersOutputSchema>;

@Injectable()
export class ListOrdersQuery {
  private readonly logger = new Logger(ListOrdersQuery.name);

  public constructor(private readonly kyckrClient: KyckrHttpClient) {}

  @Span()
  public async run(input: ListOrdersInput): Promise<ListOrdersResult> {
    try {
      const raw = await this.kyckrClient.get<unknown>('/orders', {
        startDate: input.startDate,
        endDate: input.endDate,
        isoCode: input.isoCode,
      });
      const response = ListOrdersEnvelopeSchema.parse(raw);
      return { success: true, ...response };
    } catch (err) {
      if (err instanceof KyckrApiError) {
        this.logger.warn(
          { status: err.status, correlationId: err.correlationId, msg: err.message },
          'list_orders: Kyckr API rejected request',
        );
        return {
          success: false,
          statusCode: err.status,
          message: err.message,
          correlationId: err.correlationId,
        };
      }
      throw err;
    }
  }
}
