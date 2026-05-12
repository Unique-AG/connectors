import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { KyckrApiError, KyckrHttpClient } from '../../kyckr-http.client';
import { type KyckrToolCallResult, Metrics } from '../../metrics';
import {
  KyckrBaseResponseShape,
  KyckrOrdersPageSchema,
  McpEnvelopeShape,
} from '../../schemas/kyckr-response.schemas';

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

  public constructor(
    private readonly kyckrClient: KyckrHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: ListOrdersInput): Promise<ListOrdersResult> {
    this.logger.debug(
      {
        hasStartDate: Boolean(input.startDate),
        hasEndDate: Boolean(input.endDate),
        isoCode: input.isoCode,
      },
      'list_orders: invoked',
    );
    const start = Date.now();
    let result: KyckrToolCallResult = 'success';
    try {
      const raw = await this.kyckrClient.get<unknown>('/orders', {
        startDate: input.startDate,
        endDate: input.endDate,
        isoCode: input.isoCode,
      });
      const response = ListOrdersEnvelopeSchema.parse(raw);
      this.metrics.recordCreditsConsumed('list_orders', response.cost?.value ?? 0);
      this.logger.debug(
        {
          totalCount: response.data?.totalCount,
          returned: response.data?.orders?.length ?? 0,
        },
        'list_orders: succeeded',
      );
      return { success: true, ...response };
    } catch (err) {
      result = 'error';
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
    } finally {
      this.metrics.recordToolDuration('list_orders', result, Date.now() - start);
    }
  }
}
