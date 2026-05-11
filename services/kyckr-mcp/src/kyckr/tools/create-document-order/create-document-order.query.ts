import { Inject, Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { type KyckrConfig, kyckrConfig } from '~/config';
import { KyckrApiError, KyckrHttpClient } from '../../kyckr-http.client';
import {
  KyckrBaseResponseShape,
  KyckrIdSchema,
  KyckrOrderStatusSchema,
  McpEnvelopeShape,
} from '../../schemas/kyckr.schemas';

export const CreateDocumentOrderInputSchema = z.object({
  kyckrId: KyckrIdSchema,
  productId: z
    .string()
    .trim()
    .min(1)
    .describe(
      'Product id of the document to order. Use the `id` of an entry returned by `list_company_documents`. Do not construct or guess.',
    ),
});

export type CreateDocumentOrderInput = z.infer<typeof CreateDocumentOrderInputSchema>;

const CreateOrderDataSchema = z
  .object({
    orderId: z
      .union([z.string(), z.number()])
      .optional()
      .describe(
        'Identifier of the created order. Pass to `get_order` to poll status and retrieve download links once ready.',
      ),
    status: KyckrOrderStatusSchema.optional(),
  })
  .loose()
  .describe(
    "Created order summary. Most jurisdictions return `status: 'Pending'`; poll `get_order(orderId)` until `Success` or `Failed`.",
  );

const CreateOrderEnvelopeSchema = z
  .object({
    ...KyckrBaseResponseShape,
    data: CreateOrderDataSchema.optional(),
  })
  .loose();

export const CreateDocumentOrderOutputSchema = z
  .object({
    ...McpEnvelopeShape,
    data: CreateOrderDataSchema.optional(),
  })
  .loose();

export type CreateDocumentOrderResult = z.infer<typeof CreateDocumentOrderOutputSchema>;

@Injectable()
export class CreateDocumentOrderQuery {
  private readonly logger = new Logger(CreateDocumentOrderQuery.name);

  public constructor(
    private readonly kyckrClient: KyckrHttpClient,
    @Inject(kyckrConfig.KEY)
    private readonly config: KyckrConfig,
  ) {}

  @Span()
  public async run(input: CreateDocumentOrderInput): Promise<CreateDocumentOrderResult> {
    try {
      const raw = await this.kyckrClient.post<unknown>('/orders', {
        kyckrId: input.kyckrId,
        productId: input.productId,
        customerReference: this.config.defaultCustomerReference,
        contactEmail: this.config.defaultContactEmail,
      });
      const response = CreateOrderEnvelopeSchema.parse(raw);
      return { success: true, ...response };
    } catch (err) {
      if (err instanceof KyckrApiError) {
        this.logger.warn(
          {
            status: err.status,
            kyckrId: input.kyckrId,
            productId: input.productId,
            correlationId: err.correlationId,
            msg: err.message,
          },
          'create_document_order: Kyckr API rejected request',
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
