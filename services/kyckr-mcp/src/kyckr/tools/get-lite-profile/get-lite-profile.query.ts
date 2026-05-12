import { Inject, Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { type KyckrConfig, kyckrConfig } from '~/config';
import { KyckrApiError, KyckrHttpClient } from '../../kyckr-http.client';
import { Metrics } from '../../metrics';
import {
  KyckrActivitySchema,
  KyckrAddressSchema,
  KyckrAlternativeNameSchema,
  KyckrBaseResponseShape,
  KyckrIdentifierSchema,
  KyckrIdSchema,
  KyckrNormalizedDateSchema,
  KyckrNormalizedLegalFormSchema,
  KyckrNormalizedStatusSchema,
  KyckrPreviousNameSchema,
  KyckrRegistrationTypeDetailsSchema,
  McpEnvelopeShape,
} from '../../schemas/kyckr.schemas';

export const GetLiteProfileInputSchema = z.object({
  kyckrId: KyckrIdSchema,
});

export type GetLiteProfileInput = z.infer<typeof GetLiteProfileInputSchema>;

const LiteProfileDataSchema = z
  .object({
    companyName: z
      .string()
      .optional()
      .describe('Registered company name in the language of the source registry.'),
    englishName: z
      .string()
      .optional()
      .describe(
        'English-language company name when the registry provides one. Use this for English-only contexts; otherwise prefer `companyName`.',
      ),
    aliases: z
      .array(KyckrAlternativeNameSchema)
      .optional()
      .describe('Trading names / "doing business as" names the company is also known by.'),
    previousNames: z
      .array(KyckrPreviousNameSchema)
      .optional()
      .describe(
        'Historical company names. Each entry includes when that name was in use. Helpful for matching against legacy records.',
      ),
    companyNumber: z
      .string()
      .optional()
      .describe('Company registration number issued by the registration authority.'),
    otherIdentifiers: z
      .array(KyckrIdentifierSchema)
      .optional()
      .describe(
        'Additional jurisdiction-specific identifiers (VAT, tax ID, alternative registry IDs). Use the `type` field to disambiguate.',
      ),
    taxNumber: z
      .string()
      .optional()
      .describe('Deprecated by Kyckr - prefer the matching entry in `otherIdentifiers`.'),
    registrationAuthority: z
      .string()
      .optional()
      .describe(
        'Name of the registration authority responsible for the record, e.g. "Companies House, United Kingdom".',
      ),
    registrationAuthorityCode: z
      .string()
      .optional()
      .describe('Authority code where the registry provides one.'),
    registrationType: z
      .string()
      .optional()
      .describe(
        "Present when the company's original foundational registration is held at a different (source) register than the one this profile is sourced from. Common for cross-jurisdiction or migrated entities. Inspect `registrationTypeDetails` for the source registry information.",
      ),
    registrationTypeDetails: KyckrRegistrationTypeDetailsSchema.optional(),
    address: KyckrAddressSchema.optional().describe(
      'Registered address. For the Lite profile there is typically a single address; the Enhanced profile may return multiple.',
    ),
    activity: z
      .array(KyckrActivitySchema)
      .optional()
      .describe(
        'Declared economic activities (NACE / SIC / NAICS classifications). The `Primary` entry is the main activity; `Secondary` entries are additional activities.',
      ),
    foundationDate: KyckrNormalizedDateSchema.optional().describe(
      'Date the legal entity was originally founded. May predate `registrationDate` when the entity moved between registries.',
    ),
    registrationDate: KyckrNormalizedDateSchema.optional().describe(
      'Date the entity was registered at the current registration authority.',
    ),
    lastAnnualAccountDate: KyckrNormalizedDateSchema.optional().describe(
      'Most recent annual accounts filing date at the registry, where reported.',
    ),
    legalForm: KyckrNormalizedLegalFormSchema.optional(),
    legalStatus: KyckrNormalizedStatusSchema.optional(),
    stateOfIncorporation: z
      .string()
      .optional()
      .describe('State of incorporation. US-only field; absent for non-US companies.'),
    updatedDate: KyckrNormalizedDateSchema.optional().describe(
      'When this profile was last updated at Kyckr (refresh timestamp). Use to judge how fresh the underlying data is.',
    ),
  })
  .loose()
  .describe(
    'Lite company profile data - the canonical company identification fields. Use this when you need to confirm the company exists and obtain its identification, registered address, dates, and current status. Does not include directors, shareholders, or beneficial owners (use `get_enhanced_profile` for those).',
  );

const LiteProfileEnvelopeSchema = z
  .object({
    ...KyckrBaseResponseShape,
    data: LiteProfileDataSchema.optional(),
  })
  .loose();

export const GetLiteProfileOutputSchema = z
  .object({
    ...McpEnvelopeShape,
    data: LiteProfileDataSchema.optional(),
  })
  .loose();

export type GetLiteProfileResult = z.infer<typeof GetLiteProfileOutputSchema>;

@Injectable()
export class GetLiteProfileQuery {
  private readonly logger = new Logger(GetLiteProfileQuery.name);

  public constructor(
    private readonly kyckrClient: KyckrHttpClient,
    private readonly metrics: Metrics,
    @Inject(kyckrConfig.KEY)
    private readonly config: KyckrConfig,
  ) {}

  @Span()
  public async run(input: GetLiteProfileInput): Promise<GetLiteProfileResult> {
    this.logger.debug({ kyckrId: input.kyckrId }, 'get_lite_profile: invoked');
    const start = Date.now();
    try {
      const raw = await this.kyckrClient.get<unknown>(
        `/companies/${encodeURIComponent(input.kyckrId)}/lite`,
        {
          customerReference: this.config.defaultCustomerReference,
        },
      );
      const response = LiteProfileEnvelopeSchema.parse(raw);
      this.metrics.recordToolCall('get_lite_profile', 'success');
      this.metrics.recordCreditsConsumed('get_lite_profile', response.cost);
      this.metrics.recordToolDuration('get_lite_profile', 'success', Date.now() - start);
      this.logger.debug({ kyckrId: input.kyckrId }, 'get_lite_profile: succeeded');
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
          'get_lite_profile: Kyckr API rejected request',
        );
        this.metrics.recordToolCall('get_lite_profile', 'error');
        this.metrics.recordToolDuration('get_lite_profile', 'error', Date.now() - start);
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
