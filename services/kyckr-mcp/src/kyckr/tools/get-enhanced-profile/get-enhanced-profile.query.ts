import { Inject, Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { type KyckrConfig, kyckrConfig } from '~/config';
import { KyckrApiError, KyckrHttpClient } from '../../kyckr-http.client';
import {
  KyckrActivitySchema,
  KyckrAddressSchema,
  KyckrAlternativeNameSchema,
  KyckrBaseResponseShape,
  KyckrContactDetailsSchema,
  KyckrIdentifierSchema,
  KyckrIdSchema,
  KyckrNormalizedDateSchema,
  KyckrNormalizedLegalFormSchema,
  KyckrNormalizedStatusSchema,
  KyckrPreviousNameSchema,
  KyckrRegistrationTypeDetailsSchema,
  McpEnvelopeShape,
} from '../../schemas/kyckr.schemas';

export const GetEnhancedProfileInputSchema = z.object({
  kyckrId: KyckrIdSchema,
});

export type GetEnhancedProfileInput = z.infer<typeof GetEnhancedProfileInputSchema>;

// Polymorphic representatives / UBOs are kept loose: each entry is one of
// {Person, Corporation, Other} keyed by `type`, and jurisdictions add their own extras.
// A precise discriminated union would be large and fragile for little LLM benefit.
const RepresentativeLikeSchema = z
  .object({
    type: z
      .enum(['Person', 'Corporation', 'Other'])
      .optional()
      .describe(
        'Discriminator: `Person` for natural persons, `Corporation` for corporate entities, `Other` when Kyckr cannot definitively classify.',
      ),
  })
  .loose();

const UltimateBeneficialOwnerLikeSchema = RepresentativeLikeSchema.describe(
  'A natural person or corporation identified as an Ultimate Beneficial Owner. Same `type` discriminator as representatives. Fields include `natureOfControl`, `notifiedDate`, `startDate`/`endDate`, and entity details (name, address, etc.).',
);

const EnhancedProfileDataSchema = z
  .object({
    identifiers: z
      .object({
        primaryRegistrationNumber: z
          .string()
          .optional()
          .describe('Primary corporate registration number.'),
        otherIdentifiers: z
          .array(KyckrIdentifierSchema)
          .optional()
          .describe('Additional jurisdiction-specific identifiers (VAT, tax ID, etc.).'),
      })
      .loose()
      .optional()
      .describe('Registration identifiers for the company.'),
    companyName: z.string().optional().describe('Company name as registered.'),
    englishName: z
      .string()
      .optional()
      .describe('English-language company name when the registry provides one.'),
    aliases: z
      .array(KyckrAlternativeNameSchema)
      .optional()
      .describe('Trading names / "doing business as" names.'),
    previousNames: z
      .array(KyckrPreviousNameSchema)
      .optional()
      .describe('Historical company names with their date ranges.'),
    registrationAuthority: z
      .string()
      .optional()
      .describe('Name of the registration authority responsible for the record.'),
    lastUpdated: z
      .string()
      .optional()
      .describe('When the profile data was last refreshed at the registry (ISO 8601).'),
    foundationDate: KyckrNormalizedDateSchema.optional().describe(
      'Date the legal entity was originally founded. May predate `registrationDate` when the entity moved between registries.',
    ),
    registrationDate: KyckrNormalizedDateSchema.optional().describe(
      'Date the entity was registered at the current registration authority.',
    ),
    incorporationDate: KyckrNormalizedDateSchema.optional().describe(
      'Date of incorporation, where the registry reports it distinctly from `registrationDate`.',
    ),
    dissolutionDate: KyckrNormalizedDateSchema.optional().describe(
      'Date the company was dissolved. Presence here is a strong "Inactive" signal regardless of `status.normalized`.',
    ),
    lastAnnualAccountDate: KyckrNormalizedDateSchema.optional().describe(
      'Most recent annual accounts filing date at the registry, where reported.',
    ),
    status: KyckrNormalizedStatusSchema.optional(),
    legalForm: KyckrNormalizedLegalFormSchema.optional(),
    incorporationJurisdiction: z
      .object({
        original: z.string().optional().describe('Jurisdiction of incorporation as reported.'),
      })
      .loose()
      .optional(),
    registeredAgentName: z.string().optional().describe('Name of registered agent, if any.'),
    registeredAgentAddress: z.string().optional().describe('Address of registered agent, if any.'),
    activities: z
      .array(KyckrActivitySchema)
      .optional()
      .describe('Declared economic activities (NACE / SIC / NAICS).'),
    activityDeclarations: z
      .array(
        z
          .object({
            declaration: z
              .string()
              .optional()
              .describe('Full text of the activity declaration as recorded at the registry.'),
            declarationDescription: z
              .string()
              .optional()
              .describe(
                'Section heading at the registry (e.g. "Objet social", "Business Purpose").',
              ),
            language: z.string().optional().describe('Language code, e.g. "fr", "en".'),
          })
          .loose(),
      )
      .optional()
      .describe(
        "Free-text declaration of the company's business purpose, as stated at the registry.",
      ),
    addresses: z
      .array(KyckrAddressSchema)
      .optional()
      .describe(
        'All known addresses for the company (head office, registered office, etc.). Multiple entries are common; the Lite profile collapses to one.',
      ),
    totalCapital: z
      .object({})
      .loose()
      .optional()
      .describe(
        'Total share capital summary. Fields: `totalValue` (amount), `quantity` (share count), `currency`, `type` (`Fixed` or `Variable`). May represent authorized or issued capital depending on what the registry reports — do not assume.',
      ),
    capital: z
      .array(z.object({}).loose())
      .optional()
      .describe(
        'Share-class breakdown. Each entry describes one class with state, code, title, share count, and nominal amounts. Many jurisdictions return `totalCapital` without the per-class breakdown.',
      ),
    representatives: z
      .object({
        individuals: z
          .array(RepresentativeLikeSchema)
          .optional()
          .describe(
            'Officers / directors / authorized representatives that are natural persons. Each entry has `role.normalized`, `isActive`, `startDate`/`endDate`, optional `birthdate` (partial precision per jurisdiction), and an array of `directorships` at other companies.',
          ),
        corporations: z
          .array(RepresentativeLikeSchema)
          .optional()
          .describe(
            'Officers that are corporate entities. Includes `registrationNumber`, `registrationAuthority`, and the same role / activity fields as individuals.',
          ),
      })
      .loose()
      .optional()
      .describe(
        "Authorized representatives of the company. Use this for KYC director checks. Some entries may carry `type: 'Other'` when Kyckr cannot definitively classify the entity.",
      ),
    ultimateBeneficialOwners: z
      .object({
        individuals: z
          .array(UltimateBeneficialOwnerLikeSchema)
          .optional()
          .describe('Natural-person UBOs.'),
        corporations: z
          .array(UltimateBeneficialOwnerLikeSchema)
          .optional()
          .describe('Corporate UBOs.'),
      })
      .loose()
      .optional()
      .describe(
        'Ultimate Beneficial Owners sourced from official beneficial-ownership registers (e.g. UK PSC register). Presence and completeness vary by jurisdiction; absence here does not prove the company has no UBOs.',
      ),
    contactDetails: KyckrContactDetailsSchema.optional(),
    companyRelationships: z
      .array(z.object({}).loose())
      .optional()
      .describe(
        'Relationships to other companies: subsidiaries, mergers, demergers, acquisitions. Parent / ultimate parent relationships typically appear under `representatives` instead.',
      ),
    registrationType: z
      .string()
      .optional()
      .describe(
        "Present when the company's original foundational registration is held at a different (source) register. See `registrationTypeDetails` for the source.",
      ),
    registrationTypeDetails: KyckrRegistrationTypeDetailsSchema.optional(),
    additionalInformation: z
      .object({})
      .loose()
      .optional()
      .describe(
        'Jurisdiction-specific extras Kyckr could not normalize into the main schema, e.g. cross-referenced address details. Inspect ad-hoc when needed.',
      ),
    links: z
      .object({
        document: z
          .string()
          .optional()
          .describe('URL to download an artifact of this profile, when available.'),
        data: z.string().optional().describe('URL to the structured-data form of this profile.'),
      })
      .loose()
      .optional(),
  })
  .loose()
  .describe(
    'Enhanced company profile: identification, addresses, capital, officers/representatives, ultimate beneficial owners, contact details, and registry links. Includes everything in `get_lite_profile` plus ownership/governance data.',
  );

const EnhancedProfileEnvelopeSchema = z
  .object({
    ...KyckrBaseResponseShape,
    data: EnhancedProfileDataSchema.optional(),
  })
  .loose();

export const GetEnhancedProfileOutputSchema = z
  .object({
    ...McpEnvelopeShape,
    data: EnhancedProfileDataSchema.optional(),
  })
  .loose();

export type GetEnhancedProfileResult = z.infer<typeof GetEnhancedProfileOutputSchema>;

@Injectable()
export class GetEnhancedProfileQuery {
  private readonly logger = new Logger(GetEnhancedProfileQuery.name);

  public constructor(
    private readonly kyckrClient: KyckrHttpClient,
    @Inject(kyckrConfig.KEY)
    private readonly config: KyckrConfig,
  ) {}

  @Span()
  public async run(input: GetEnhancedProfileInput): Promise<GetEnhancedProfileResult> {
    try {
      const raw = await this.kyckrClient.get<unknown>(
        `/companies/${encodeURIComponent(input.kyckrId)}/enhanced`,
        { customerReference: this.config.defaultCustomerReference },
      );
      const response = EnhancedProfileEnvelopeSchema.parse(raw);
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
          'get_enhanced_profile: Kyckr API rejected request',
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
