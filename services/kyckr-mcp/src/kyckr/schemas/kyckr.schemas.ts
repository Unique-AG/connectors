import * as z from 'zod';

// Shared Zod schemas mirroring the Kyckr v2 API component schemas.
// Schemas are intentionally `.loose()` so new Kyckr fields still reach the LLM.

export const KyckrCostSchema = z
  .object({
    type: z.string().optional().describe('Cost dimension reported by Kyckr, typically "credit".'),
    value: z
      .number()
      .optional()
      .describe(
        'Credits consumed by this call. `0` for free endpoints (search, list orders, get order). Greater than `0` for billed endpoints (lite/enhanced profile, document orders).',
      ),
  })
  .loose()
  .describe('Credit cost incurred by the upstream Kyckr call.');

export const KyckrBaseResponseShape = {
  correlationId: z
    .string()
    .optional()
    .describe('Kyckr correlation ID. Include in any support request about this call.'),
  customerReference: z
    .string()
    .optional()
    .describe(
      'Customer reference echoed by Kyckr for usage reconciliation. Matches the value forwarded on the request.',
    ),
  timeStamp: z
    .string()
    .optional()
    .describe('UTC timestamp reported by Kyckr for the upstream response.'),
  details: z.string().optional().describe('Kyckr-reported response status detail, e.g. "Success".'),
  cost: KyckrCostSchema.optional(),
} as const;

// The standard envelope of `success`/`message` (added by this MCP server) plus the
// fields Kyckr returns at the top level (correlationId, cost, …). Tools compose this
// with their own `data` schema.
export const McpEnvelopeShape = {
  success: z
    .boolean()
    .describe(
      '`true` if Kyckr returned a 2xx response; `false` if the call was rejected (auth, validation, not-found, rate-limit, etc).',
    ),
  statusCode: z
    .number()
    .int()
    .optional()
    .describe(
      'Upstream HTTP status returned by Kyckr when `success` is `false`. Common values: `400` (bad request — usually missing/invalid parameter), `401` (auth — server-side credential issue), `403` (entitlement — feature not on account), `404` (kyckrId / orderId not found), `405` (jurisdiction requires async ordering), `429` (rate-limited). Use this to decide whether to retry, surface to the user, or escalate.',
    ),
  message: z
    .string()
    .optional()
    .describe(
      'Human-readable error description when `success` is `false`. Sourced from Kyckr `data.detail` when present, then `data.title`, then the raw response body. Show to the user verbatim.',
    ),
  ...KyckrBaseResponseShape,
} as const;

export const KyckrNormalizedDateSchema = z
  .object({
    original: z
      .string()
      .optional()
      .describe('Date as formatted at the source registry. Format varies by jurisdiction.'),
    normalized: z
      .string()
      .optional()
      .describe(
        'Date in ISO 8601. Precision matches what the source provides: full date `YYYY-MM-DD`, or partial `YYYY-MM` / `YYYY` when only month or year is known. Prefer this over `original` for display and comparison.',
      ),
  })
  .loose()
  .describe(
    'Date value from the registry, with both the raw form and an ISO-normalized form. Use `normalized` for any logic; show `original` only when the source format is itself meaningful.',
  );

export const KyckrNormalizedLegalFormSchema = z
  .object({
    original: z
      .string()
      .optional()
      .describe(
        'Legal form as described at the source registry (free text, jurisdiction-specific).',
      ),
    normalized: z
      .string()
      .optional()
      .describe('Legal form mapped to a Kyckr controlled dictionary.'),
  })
  .loose()
  .describe(
    'Company legal form (e.g. "Private Company Limited by Shares"). `original` for display.',
  );

export const KyckrNormalizedStatusSchema = z
  .object({
    original: z
      .string()
      .optional()
      .describe('Legal status as described at source (free text, jurisdiction-specific).'),
    normalized: z
      .enum(['Active', 'Inactive', 'Distressed', 'Other'])
      .optional()
      .describe(
        'Kyckr-normalized status. Use this for decisioning: `Active` means the company is currently in good standing on the register; `Inactive` means struck-off / dissolved; `Distressed` means liquidation / administration / similar; `Other` means a registry-specific state that does not map cleanly.',
      ),
  })
  .loose()
  .describe('Current registration status of the company.');

export const KyckrAddressSchema = z
  .object({
    identifier: z
      .string()
      .nullish()
      .describe(
        'Stable identifier for this address within the profile. Used to cross-reference into enhanced-profile `additionalInformation.addressInformation` entries.',
      ),
    type: z.string().optional().describe('Address role, e.g. "Head Office", "Registered Address".'),
    fullAddress: z
      .string()
      .optional()
      .describe('Address as a single human-readable string. Best field to display to the user.'),
    rawAddressLines: z
      .array(z.string())
      .optional()
      .describe('Address lines as returned by the registry, without normalization.'),
    buildingName: z.string().optional().describe('Building name, e.g. "The Chrysler Building".'),
    streetNumber: z.string().optional().describe('Street number portion, e.g. "18" or "21A".'),
    streetName: z.string().optional().describe('Street name.'),
    city: z.string().optional().describe('City or town.'),
    postcode: z.string().optional().describe('Primary postal code.'),
    municipality: z
      .string()
      .optional()
      .describe('Administrative sub-region, e.g. a French commune or US county.'),
    region: z.string().optional().describe('Administrative region, e.g. a US state or UK county.'),
    country: z.string().optional().describe('Country (registry-provided form).'),
    isoCode: z
      .string()
      .optional()
      .describe('Country in ISO 3166 alpha-2, e.g. "GB", "IE". Use this for jurisdiction logic.'),
    secondaryPostalCode: z
      .string()
      .optional()
      .describe('Secondary postal code where applicable, e.g. a French CEDEX.'),
  })
  .loose()
  .describe(
    'Standardized address. `fullAddress` is the safest field to display; structured fields are populated where the registry provides them.',
  );

export const KyckrActivitySchema = z
  .object({
    code: z
      .string()
      .optional()
      .describe(
        'Activity code in the scheme indicated by `classificationScheme`, e.g. NACE `63120`.',
      ),
    description: z
      .string()
      .optional()
      .describe('Human-readable description of the activity, e.g. "Web portals".'),
    classificationScheme: z
      .enum(['NACE', 'SIC', 'SIC07', 'NAICS'])
      .optional()
      .describe(
        'Classification scheme used for `code`. NACE for EU registries, SIC/SIC07 for UK/US, NAICS for US/Canada.',
      ),
    type: z
      .enum(['Primary', 'Secondary'])
      .optional()
      .describe(
        "`Primary` is the company's main declared activity; `Secondary` are additional activities.",
      ),
  })
  .loose()
  .describe("An entry from the company's declared economic activities.");

export const KyckrIdentifierSchema = z
  .object({
    value: z
      .string()
      .optional()
      .describe('The identifier value, e.g. "IT12345678912" for a VAT number.'),
    type: z
      .string()
      .optional()
      .describe(
        'Kyckr standardized type code for the identifier. Examples: `IT_VAT_CD` (Italian VAT), `IT_TAX_CD` (Italian Codice Fiscale), `IT_REA_CD` (REA trade register).',
      ),
  })
  .loose()
  .describe(
    'A jurisdiction-specific identifier attached to the company (VAT, tax ID, alternative registry IDs).',
  );

export const KyckrAlternativeNameSchema = z
  .object({
    name: z.string().optional().describe('Alternative name used by the company.'),
    type: z
      .string()
      .optional()
      .describe(
        'Kind of alternative name, e.g. "Trading Name", "Business Name", "Doing Business As".',
      ),
  })
  .loose()
  .describe(
    'Alternative name (trading name / DBA) the company is known by, in addition to its registered name.',
  );

export const KyckrPreviousNameSchema = z
  .object({
    name: z.string().optional().describe('Former registered company name.'),
    startDate: KyckrNormalizedDateSchema.optional().describe(
      'Date the company started using this name.',
    ),
    endDate: KyckrNormalizedDateSchema.optional().describe(
      'Date the company stopped using this name (when it changed to the current name or another former one).',
    ),
  })
  .loose()
  .describe('A historical name of the company prior to its current registered name.');

export const KyckrRegistrationTypeDetailsSchema = z
  .object({
    originalCode: z.string().optional().describe('Non-standard code for the source registry.'),
    originalDescription: z
      .string()
      .optional()
      .describe('Description text for the source registry.'),
    normalizedCode: z
      .string()
      .optional()
      .describe('ISO code for the country/province/state of the source registry.'),
    normalizedDescription: z
      .string()
      .optional()
      .describe('Country and state description of the foreign source registry.'),
  })
  .loose()
  .describe(
    "Details of the company's original foundational registration when it is held in a different register than the one Kyckr is reporting from (cross-jurisdiction registration).",
  );
