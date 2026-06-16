import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { KyckrApiError, KyckrHttpClient } from '../../kyckr-http.client';
import { type KyckrToolCallResult, Metrics } from '../../metrics';
import {
  KyckrBaseResponseShape,
  KyckrOrderDetailsAgentSchema,
  KyckrOrderDetailsSchema,
  McpEnvelopeShape,
} from '../../schemas/kyckr-response.schemas';
import { appendDetail, fetchOrder, stripLinks } from '../_shared/fetch-order';

export const GetOrderInputSchema = z.object({
  orderId: z
    .union([z.string().trim().min(1), z.number().int()])
    .transform((v) => String(v))
    .describe(
      'Order id returned by `create_document_order.data.orderId` or seen in `list_orders.data.orders[].orderId`. May be a string or a number - both accepted; pass the value as-is.',
    ),
});

export type GetOrderInput = z.infer<typeof GetOrderInputSchema>;

const GetOrderEnvelopeSchema = z
  .object({
    ...KyckrBaseResponseShape,
    data: KyckrOrderDetailsSchema.optional(),
  })
  .loose();

export const GetOrderOutputSchema = z
  .object({
    ...McpEnvelopeShape,
    data: KyckrOrderDetailsAgentSchema.optional(),
  })
  .loose();

export type GetOrderResult = z.infer<typeof GetOrderOutputSchema>;

@Injectable()
export class GetOrderQuery {
  private readonly logger = new Logger(GetOrderQuery.name);

  public constructor(
    private readonly kyckrClient: KyckrHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: GetOrderInput): Promise<GetOrderResult> {
    this.logger.debug({ orderId: input.orderId }, 'get_order: invoked');
    const start = Date.now();
    let result: KyckrToolCallResult = 'success';
    try {
      const raw = await this.kyckrClient.get<unknown>(
        `/orders/${encodeURIComponent(input.orderId)}`,
      );
      const response = GetOrderEnvelopeSchema.parse(raw);
      this.metrics.recordCreditsConsumed('get_order', response.cost?.value ?? 0);
      this.logger.debug(
        { orderId: input.orderId, status: response.data?.status },
        'get_order: succeeded',
      );

      const dataWithoutLinks = stripLinks(response.data);

      if (response.data?.status !== 'Success') {
        return {
          success: true,
          ...response,
          data: dataWithoutLinks,
        };
      }

      const fetched = await fetchOrder(this.kyckrClient, input.orderId, response.data.status);
      const detail = fetched.kind === 'absent' ? fetched.detail : undefined;
      const documentJson = fetched.kind === 'json' ? fetched.documentJson : undefined;

      return {
        success: true,
        ...response,
        details: appendDetail(response.details, detail),
        data: { ...dataWithoutLinks, documentJson },
      };
    } catch (err) {
      result = 'error';
      if (err instanceof KyckrApiError) {
        this.logger.warn(
          {
            status: err.status,
            orderId: input.orderId,
            correlationId: err.correlationId,
            msg: err.message,
          },
          'get_order: Kyckr API rejected request',
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
      this.metrics.recordToolDuration('get_order', result, start);
    }
  }
}
