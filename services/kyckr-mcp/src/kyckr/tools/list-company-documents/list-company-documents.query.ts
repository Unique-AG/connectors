import { Inject, Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { type KyckrConfig, kyckrConfig } from '~/config';
import { KyckrApiError, KyckrHttpClient } from '../../kyckr-http.client';
import { Metrics } from '../../metrics';
import {
  KyckrBaseResponseShape,
  KyckrDocumentDescriptionSchema,
  KyckrIdSchema,
  McpEnvelopeShape,
} from '../../schemas/kyckr.schemas';

export const ListCompanyDocumentsInputSchema = z.object({
  kyckrId: KyckrIdSchema,
  continuationKey: z
    .string()
    .trim()
    .min(1)
    .optional()
    .describe(
      'Opaque pagination token from a previous response. Pass it back to fetch the next page. Omit on the first call.',
    ),
});

export type ListCompanyDocumentsInput = z.infer<typeof ListCompanyDocumentsInputSchema>;

const ListCompanyDocumentsEnvelopeSchema = z
  .object({
    ...KyckrBaseResponseShape,
    data: z
      .array(KyckrDocumentDescriptionSchema)
      .optional()
      .describe('Documents available to order for the company.'),
    continuationKey: z
      .string()
      .nullish()
      .describe(
        'When non-null, pass back as `continuationKey` to retrieve the next page. When null or absent, there are no more pages.',
      ),
  })
  .loose();

export const ListCompanyDocumentsOutputSchema = z
  .object({
    ...McpEnvelopeShape,
    data: z
      .array(KyckrDocumentDescriptionSchema)
      .optional()
      .describe('Documents available to order for the company.'),
    continuationKey: z
      .string()
      .nullish()
      .describe(
        'Opaque pagination token. When non-null, pass it back as `continuationKey` on the next `list_company_documents` call to fetch more results. When null or absent, this is the final page.',
      ),
  })
  .loose();

export type ListCompanyDocumentsResult = z.infer<typeof ListCompanyDocumentsOutputSchema>;

@Injectable()
export class ListCompanyDocumentsQuery {
  private readonly logger = new Logger(ListCompanyDocumentsQuery.name);

  public constructor(
    private readonly kyckrClient: KyckrHttpClient,
    private readonly metrics: Metrics,
    @Inject(kyckrConfig.KEY)
    private readonly config: KyckrConfig,
  ) {}

  @Span()
  public async run(input: ListCompanyDocumentsInput): Promise<ListCompanyDocumentsResult> {
    this.logger.debug(
      { kyckrId: input.kyckrId, hasContinuation: Boolean(input.continuationKey) },
      'list_company_documents: invoked',
    );
    try {
      const raw = await this.kyckrClient.get<unknown>(
        `/companies/${encodeURIComponent(input.kyckrId)}/documents`,
        {
          customerReference: this.config.defaultCustomerReference,
          continuationKey: input.continuationKey,
        },
      );
      const response = ListCompanyDocumentsEnvelopeSchema.parse(raw);
      this.metrics.recordToolCall('list_company_documents', 'success');
      this.metrics.recordCreditsConsumed('list_company_documents', response.cost);
      this.logger.debug(
        {
          kyckrId: input.kyckrId,
          documentCount: response.data?.length ?? 0,
          hasMore: Boolean(response.continuationKey),
        },
        'list_company_documents: succeeded',
      );
      return { success: true, ...response };
    } catch (err) {
      if (err instanceof KyckrApiError) {
        this.logger.warn(
          {
            status: err.status,
            kyckrId: input.kyckrId,
            correlationId: err.correlationId,
            msg: err.message,
          },
          'list_company_documents: Kyckr API rejected request',
        );
        this.metrics.recordToolCall('list_company_documents', 'error');
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
