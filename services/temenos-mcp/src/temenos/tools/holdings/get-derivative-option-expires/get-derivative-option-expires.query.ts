import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';
import { Metrics } from '../../../metrics';

export const GetDerivativeOptionExpiresInputSchema = z.object({
  tradeStatus: z.string().optional().describe("Trade status: ACTIVE or CLOSED"),
  lot: z.string().optional().describe("Number of lots or contracts traded"),
  tradeType: z.string().optional().describe("Contract type: FUTURE, OPTION, or STOCK"),
  syTransactionReference: z.string().optional().describe("Structured product reference for the trade"),
  PndSett: z.string().optional().describe("ID of any pending DX.CLOSEOUT for this customer"),
  portfolioId: z.string().optional().describe("ID of the portfolio or security account"),
  instrumentId: z.string().optional().describe("Identifier of the instrument"),
  maturityDate: z.string().optional().describe("Maturity date of the contract"),
  strikePrice: z.string().optional().describe("Price at which the option holder may buy (Call) or sell (Put) the underlying"),
  callOrPut: z.string().optional().describe("Option type: CALL or PUT"),
  tradeCurrency: z.string().optional().describe("Settlement currency for the trade"),
  contractCurrency: z.string().optional().describe("Contract currency"),
  optionStyle: z.string().optional().describe("Settlement rule: AMERICAN or EUROPEAN"),
  referenceId: z.string().optional().describe("Unique identifier of the activity"),
});

export type GetDerivativeOptionExpiresInput = z.infer<typeof GetDerivativeOptionExpiresInputSchema>;

export const GetDerivativeOptionExpiresOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetDerivativeOptionExpiresResult = z.infer<typeof GetDerivativeOptionExpiresOutputSchema>;

@Injectable()
export class GetDerivativeOptionExpiresQuery {
  private readonly logger = new Logger(GetDerivativeOptionExpiresQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: GetDerivativeOptionExpiresInput): Promise<GetDerivativeOptionExpiresResult> {
    this.logger.debug({}, 'get_derivative_option_expires: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>('/holdings/instruments/options/expires', {
        tradeStatus: input.tradeStatus,
        lot: input.lot,
        tradeType: input.tradeType,
        syTransactionReference: input.syTransactionReference,
        PndSett: input.PndSett,
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
      this.metrics.recordToolDuration('get_derivative_option_expires', result, start);
    }
  }
}
