import { Inject, Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { type KyckrConfig, kyckrConfig } from '~/config';
import { KyckrApiError, KyckrHttpClient } from '../../kyckr-http.client';
import { type KyckrToolCallResult, Metrics } from '../../metrics';
import { KyckrOrderDocumentSchema } from '../../schemas/kyckr-order-document.schemas';
import {
  KyckrBaseResponseShape,
  KyckrIdSchema,
  KyckrOrderStatusSchema,
  McpEnvelopeShape,
} from '../../schemas/kyckr-response.schemas';
import { appendDetail, fetchOrder, stripLinks } from '../_shared/fetch-order';
import type { McpToolResult } from '../_shared/mcp-tool-result';

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
        'Identifier of the created order. Pass to `get_order` to poll status and retrieve the document body once ready.',
      ),
    status: KyckrOrderStatusSchema.optional(),
    documentJson: KyckrOrderDocumentSchema.optional().describe(
      'Parsed structured view of the ordered document, populated when the order completes immediately (`status === "Success"`). Field names are PascalCase (Kyckr download-endpoint convention). The JSON view is attempted for every `Success` order regardless of the document\'s nominal format; absent for `Pending` / `Failed` orders and when the registry has no JSON projection - in that case the tool response attaches the official PDF as an embedded resource block instead.',
    ),
  })
  .loose()
  .describe(
    "Created order summary. Most jurisdictions return `status: 'Pending'`; poll `get_order(orderId)` until `data.documentJson` is populated (or a PDF resource is attached) or `status` is `Failed`. Fast jurisdictions occasionally return `Success` immediately, in which case the document body is already delivered with this call.",
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

export type CreateDocumentOrderStructured = z.infer<typeof CreateDocumentOrderOutputSchema>;
export type CreateDocumentOrderResult = McpToolResult<CreateDocumentOrderStructured>;

@Injectable()
export class CreateDocumentOrderQuery {
  private readonly logger = new Logger(CreateDocumentOrderQuery.name);

  public constructor(
    private readonly kyckrClient: KyckrHttpClient,
    private readonly metrics: Metrics,
    @Inject(kyckrConfig.KEY)
    private readonly config: KyckrConfig,
  ) {}

  @Span()
  public async run(input: CreateDocumentOrderInput): Promise<CreateDocumentOrderResult> {
    this.logger.debug(
      { kyckrId: input.kyckrId, productId: input.productId },
      'create_document_order: invoked',
    );
    const start = Date.now();
    let result: KyckrToolCallResult = 'success';
    try {
      const raw = await this.kyckrClient.post<unknown>('/orders', {
        kyckrId: input.kyckrId,
        productId: input.productId,
        customerReference: this.config.defaultCustomerReference,
        contactEmail: this.config.defaultContactEmail,
      });
      const response = CreateOrderEnvelopeSchema.parse(raw);
      this.metrics.recordCreditsConsumed('create_document_order', response.cost?.value ?? 0);
      this.logger.debug(
        {
          kyckrId: input.kyckrId,
          productId: input.productId,
          orderId: response.data?.orderId,
          status: response.data?.status,
        },
        'create_document_order: succeeded',
      );

      const orderId = response.data?.orderId;
      const dataWithoutLinks = stripLinks(response.data);

      if (response.data?.status !== 'Success' || orderId === undefined) {
        return {
          success: true,
          ...response,
          data: dataWithoutLinks,
        };
      }

      const fetched = await fetchOrder(this.kyckrClient, String(orderId), response.data.status);
      const detail = fetched.kind === 'absent' ? fetched.detail : undefined;
      const documentJson = fetched.kind === 'json' ? fetched.documentJson : undefined;

      const structured: CreateDocumentOrderStructured = {
        success: true,
        ...response,
        details: appendDetail(response.details, detail),
        data: { ...dataWithoutLinks, documentJson },
      };

      if (fetched.kind === 'pdf') {
        CreateDocumentOrderOutputSchema.parse(structured);
        return {
          structuredContent: structured,
          content: [
            { type: 'text', text: JSON.stringify(structured, null, 2) },
            {
              type: 'resource',
              resource: {
                uri: `kyckr-order://${orderId}/document.pdf`,
                mimeType: 'application/pdf',
                blob: fetched.pdfBase64,
              },
            },
          ],
        };
      }

      return structured;
    } catch (err) {
      result = 'error';
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
    } finally {
      this.metrics.recordToolDuration('create_document_order', result, start);
    }
  }
}
