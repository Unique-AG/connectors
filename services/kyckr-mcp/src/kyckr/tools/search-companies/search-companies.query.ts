import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { KyckrApiError, KyckrHttpClient } from '../../kyckr-http.client';
import { Metrics } from '../../metrics';
import { KyckrBaseResponseShape, McpEnvelopeShape } from '../../schemas/kyckr-response.schemas';

export const SearchCompaniesInputSchema = z
  .object({
    name: z.string().trim().min(1).optional().describe('Company name to search for.'),
    companyNumber: z
      .string()
      .trim()
      .min(1)
      .optional()
      .describe('Company registration number to search for.'),
    isoCode: z
      .string()
      .trim()
      .toUpperCase()
      .regex(/^[A-Z]{2}$/, 'Must be a 2-letter ISO 3166 alpha-2 code, e.g. GB, IE, AU.')
      .optional()
      .describe(
        'Optional ISO 3166 alpha-2 jurisdiction code, e.g. GB or AU. Use when the country is known.',
      ),
  })
  .refine((input) => Boolean(input.name) || Boolean(input.companyNumber), {
    message: 'Provide either `name` or `companyNumber`.',
    path: ['name'],
  });

export type SearchCompaniesInput = z.infer<typeof SearchCompaniesInputSchema>;

const SearchResultItemSchema = z
  .object({
    id: z
      .string()
      .describe(
        'KyckrId for the company. Pass as `kyckrId` to lite/enhanced profile, documents, and order tools.',
      ),
    companyName: z.string().describe('Company name as registered.'),
    englishName: z
      .string()
      .optional()
      .describe('English-language company name, when the registry provides one.'),
    companyNumber: z.string().optional().describe('Registry identifier for the company.'),
    address: z.string().optional().describe('Registered address as a single string.'),
    status: z.string().optional().describe('Registry status, e.g. "Active" or "Dissolved".'),
    type: z.string().optional().describe('Legal form / company type.'),
    startDate: z
      .string()
      .optional()
      .describe('Registration or foundation date in ISO 8601 (YYYY-MM-DD).'),
    registrationAuthority: z
      .string()
      .optional()
      .describe("Registration authority maintaining the company's records."),
    isPreviousName: z
      .boolean()
      .optional()
      .describe(
        'True when this hit matches a previous (historical) name of the company. Only set for name searches.',
      ),
  })
  .loose();

const KyckrSearchEnvelopeSchema = z
  .object({
    ...KyckrBaseResponseShape,
    data: z
      .array(SearchResultItemSchema)
      .optional()
      .describe(
        'Companies matched by the search. Empty array when the registry has no matches. Absent on error.',
      ),
  })
  .loose();

export const SearchCompaniesOutputSchema = z
  .object({
    ...McpEnvelopeShape,
    data: z
      .array(SearchResultItemSchema)
      .optional()
      .describe(
        'Companies matched by the search. Empty array when the registry has no matches. Absent on error.',
      ),
  })
  .loose();

export type SearchCompaniesResult = z.infer<typeof SearchCompaniesOutputSchema>;

@Injectable()
export class SearchCompaniesQuery {
  private readonly logger = new Logger(SearchCompaniesQuery.name);

  public constructor(
    private readonly kyckrClient: KyckrHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: SearchCompaniesInput): Promise<SearchCompaniesResult> {
    this.logger.debug(
      { hasName: Boolean(input.name), companyNumber: input.companyNumber, isoCode: input.isoCode },
      'search_companies: invoked',
    );
    const start = Date.now();
    try {
      const raw = await this.kyckrClient.get<unknown>('/companies', {
        name: input.name,
        companyNumber: input.companyNumber,
        isoCode: input.isoCode,
      });
      const response = KyckrSearchEnvelopeSchema.parse(raw);
      this.metrics.recordToolCall('search_companies', 'success');
      this.metrics.recordCreditsConsumed('search_companies', response.cost);
      this.metrics.recordToolDuration('search_companies', 'success', Date.now() - start);
      this.logger.debug({ resultCount: response.data?.length ?? 0 }, 'search_companies: succeeded');

      return { success: true, ...response };
    } catch (err) {
      if (err instanceof KyckrApiError) {
        this.logger.warn(
          { status: err.status, correlationId: err.correlationId, msg: err.message },
          'search_companies: Kyckr API rejected request',
        );
        this.metrics.recordToolCall('search_companies', 'error');
        this.metrics.recordToolDuration('search_companies', 'error', Date.now() - start);
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
