import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { Metrics } from '../../../metrics';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';

export const GetDerivativeOptionAssignsInputSchema = z.object({
  tradeStatus: z.string().optional().describe('Trade status: ACTIVE or CLOSED'),
  lot: z.string().optional().describe('Number of lots or contracts traded'),
  tradeType: z.string().optional().describe('Contract type: FUTURE, OPTION, or STOCK'),
  syTransactionReference: z
    .string()
    .optional()
    .describe('Structured product reference for the trade'),
  PndSett: z.string().optional().describe('ID of any pending DX.CLOSEOUT for this customer'),
  dxCloseoutPendingId: z.string().optional().describe('DX.CLOSEOUT pending ID for this customer'),
  buyOrSell: z.string().optional().describe('Whether the customer is buying or selling'),
  portfolioId: z.string().optional().describe('ID of the portfolio or security account'),
  instrumentId: z.string().optional().describe('Identifier of the instrument'),
  maturityDate: z.string().optional().describe('Maturity date of the contract'),
  strikePrice: z
    .string()
    .optional()
    .describe('Price at which the option holder may buy (Call) or sell (Put) the underlying'),
  callOrPut: z.string().optional().describe('Option type: CALL or PUT'),
  tradeCurrency: z.string().optional().describe('Settlement currency for the trade'),
  contractCurrency: z.string().optional().describe('Contract currency'),
  optionStyle: z
    .string()
    .optional()
    .describe('Settlement rule: AMERICAN (exercise any time) or EUROPEAN (exercise at expiry)'),
  referenceId: z.string().optional().describe('Unique identifier of the activity'),
});

export type GetDerivativeOptionAssignsInput = z.infer<typeof GetDerivativeOptionAssignsInputSchema>;

export const GetDerivativeOptionAssignsOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetDerivativeOptionAssignsResult = z.infer<
  typeof GetDerivativeOptionAssignsOutputSchema
>;

@Injectable()
export class GetDerivativeOptionAssignsQuery {
  private readonly logger = new Logger(GetDerivativeOptionAssignsQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(
    input: GetDerivativeOptionAssignsInput,
  ): Promise<GetDerivativeOptionAssignsResult> {
    this.logger.debug({}, 'get_derivative_option_assigns: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>('/holdings/instruments/options/assigns', {
        tradeStatus: input.tradeStatus,
        lot: input.lot,
        tradeType: input.tradeType,
        syTransactionReference: input.syTransactionReference,
        PndSett: input.PndSett,
        dxCloseoutPendingId: input.dxCloseoutPendingId,
        buyOrSell: input.buyOrSell,
        portfolioId: input.portfolioId,
        instrumentId: input.instrumentId,
        maturityDate: input.maturityDate,
        strikePrice: input.strikePrice,
        callOrPut: input.callOrPut,
        tradeCurrency: input.tradeCurrency,
        contractCurrency: input.contractCurrency,
        optionStyle: input.optionStyle,
        referenceId: input.referenceId,
      });
      return { success: true, data };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_derivative_option_assigns', result, start);
    }
  }
}
