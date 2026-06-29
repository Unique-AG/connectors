import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { Metrics } from '../../../metrics';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';

export const GetUtilityBeneficiariesInputSchema = z.object({
  productName: z.string().optional().describe('Product name for this account'),
  recordId: z.string().optional().describe('Unique identifier of an entity'),
  beneficiaryAccountId: z
    .string()
    .optional()
    .describe('Unique account identifier of the beneficiary'),
  bankSortCode: z
    .string()
    .optional()
    .describe('Sort code or national clearing code of the beneficiary bank'),
  transactionType: z.string().optional().describe('Transaction type, e.g. ACPX or OTPX'),
  paymentProduct: z.string().optional().describe('Preferred payment product for this beneficiary'),
  companyName: z.string().optional().describe('Company in which the payment is processed'),
  beneficiaryIBAN: z
    .string()
    .optional()
    .describe('IBAN of the beneficiary account for international transfers'),
  owningCustomerId: z
    .string()
    .optional()
    .describe('Customer ID to which the beneficiary is linked'),
});

export type GetUtilityBeneficiariesInput = z.infer<typeof GetUtilityBeneficiariesInputSchema>;

export const GetUtilityBeneficiariesOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetUtilityBeneficiariesResult = z.infer<typeof GetUtilityBeneficiariesOutputSchema>;

@Injectable()
export class GetUtilityBeneficiariesQuery {
  private readonly logger = new Logger(GetUtilityBeneficiariesQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: GetUtilityBeneficiariesInput): Promise<GetUtilityBeneficiariesResult> {
    this.logger.debug({}, 'get_utility_beneficiaries: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>('/reference/beneficiaries/utilityBeneficiaries', {
        productName: input.productName,
        recordId: input.recordId,
        beneficiaryAccountId: input.beneficiaryAccountId,
        bankSortCode: input.bankSortCode,
        transactionType: input.transactionType,
        paymentProduct: input.paymentProduct,
        companyName: input.companyName,
        beneficiaryIBAN: input.beneficiaryIBAN,
        owningCustomerId: input.owningCustomerId,
      });
      return { success: true, data };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_utility_beneficiaries', result, start);
    }
  }
}
