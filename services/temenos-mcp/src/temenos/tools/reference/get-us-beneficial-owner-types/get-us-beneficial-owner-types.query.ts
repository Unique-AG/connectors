import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { Metrics } from '../../../metrics';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';
import { TemenosHeaderSchema, TitledRecordsSchema, toTitledRecords } from '../../../titled-records';

export const GetUsBeneficialOwnerTypesInputSchema = z.object({});

export type GetUsBeneficialOwnerTypesInput = z.infer<typeof GetUsBeneficialOwnerTypesInputSchema>;

export const GetUsBeneficialOwnerTypesOutputSchema = z
  .object({
    success: z.boolean(),
    data: TitledRecordsSchema.optional(),
    header: TemenosHeaderSchema.optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetUsBeneficialOwnerTypesResult = z.infer<typeof GetUsBeneficialOwnerTypesOutputSchema>;

@Injectable()
export class GetUsBeneficialOwnerTypesQuery {
  private readonly logger = new Logger(GetUsBeneficialOwnerTypesQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(_input: Record<string, never>): Promise<GetUsBeneficialOwnerTypesResult> {
    this.logger.debug({}, 'get_us_beneficial_owner_types: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const response = await this.client.get<unknown>(
        '/reference/us/beneficialOwnerTypes',
        undefined,
      );
      return { success: true, ...toTitledRecords(response, 'Beneficial owner type') };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_us_beneficial_owner_types', result, start);
    }
  }
}
