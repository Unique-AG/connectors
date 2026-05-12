import * as z from 'zod';

// Shared Zod response schemas mirroring the Kyckr v2 API component schemas.
// Schemas are intentionally `.loose()` so new Kyckr fields still reach the LLM.

export const KyckrIdSchema = z
  .string()
  .trim()
  .min(1)
  .describe(
    'Kyckr company id returned by `search_companies` as the result `id`, e.g. "GB|MTE2NTUyOTA". Pass the exact value from search; do not construct or modify it.',
  );

export const KyckrCostSchema = z
  .object({
    type: z
      .string()
      .optional()
      .describe('Cost dimension, e.g. `"credit"`. Kyckr currently always reports credits.'),
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
      'Upstream HTTP status returned by Kyckr when `success` is `false`. Common values: `400` (bad request - usually missing/invalid parameter), `401` (auth - server-side credential issue), `403` (entitlement - feature not on account), `404` (kyckrId / orderId not found), `405` (jurisdiction requires async ordering), `429` (rate-limited). Use this to decide whether to retry, surface to the user, or escalate.',
    ),
  message: z
    .string()
    .optional()
    .describe(
      'Human-readable error description when `success` is `false`, sourced from Kyckr. Surface to the user; rephrase if it sounds too low-level.',
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
        'Date in ISO 8601. Usually `YYYY-MM-DD`; some registries return `YYYY-MM` precision (most commonly UK director birthdates). Prefer this over `original` for display and comparison.',
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
    country: z
      .string()
      .optional()
      .describe(
        'Country in the form the registry uses (unnormalized). For jurisdiction logic, prefer `isoCode`.',
      ),
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
        'Kyckr standardized type code for the identifier. Encodes both the jurisdiction and the kind of ID - e.g. `IT_VAT_CD` (Italian VAT), `IT_TAX_CD` (Italian Codice Fiscale), `IT_REA_CD` (Italian REA trade register). Other jurisdictions follow the same `{ISO}_{KIND}_CD` pattern.',
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

export const KyckrContactDetailsSchema = z
  .object({
    email: z.string().optional().describe('Primary email address for the company.'),
    fax: z.string().optional().describe('Primary fax number.'),
    telNumber: z.string().optional().describe('Primary phone number.'),
    website: z.string().optional().describe('Primary website URL.'),
  })
  .loose()
  .describe('Company contact details where the registry reports them.');

export const KyckrOrderStatusSchema = z
  .enum(['Success', 'Pending', 'Failed'])
  .describe(
    'Kyckr order status. `Success` means the document is ready - use `data.links.document` / `data.links.data` to fetch it. `Pending` means still processing - re-poll via `get_order` (when ordering, the `deliveryTimeMinutes` from `list_company_documents` is a reasonable initial wait). `Failed` means the order will not complete; surface to the user.',
  );

export const KyckrOrderDetailsSchema = z
  .object({
    orderId: z
      .union([z.string(), z.number()])
      .optional()
      .describe(
        'Kyckr order ID. May be a number or a string. Pass to `get_order` to refresh status or fetch download links.',
      ),
    orderDate: z.string().optional().describe('When the order was placed (ISO 8601 datetime).'),
    customerReference: z
      .string()
      .optional()
      .describe('Customer reference attached when the order was placed.'),
    status: KyckrOrderStatusSchema.optional(),
    cost: KyckrCostSchema.optional(),
    user: z
      .string()
      .optional()
      .describe(
        'Reference to the Kyckr user that placed the order. Informational; usually not surfaced.',
      ),
    productDetails: z
      .object({
        productName: z.string().optional().describe('Human-readable name of the ordered product.'),
        productId: z
          .string()
          .optional()
          .describe('Same value as the `id` returned by `list_company_documents`.'),
        productCategory: z
          .string()
          .optional()
          .describe('Product category, e.g. "Financial Information".'),
      })
      .loose()
      .optional()
      .describe('What was ordered - the document or profile product details.'),
    companyDetails: z
      .object({
        companyName: z.string().optional().describe('Company the order relates to.'),
        companyNumber: z.string().optional().describe('Company registration number.'),
        kyckrId: z.string().optional().describe('KyckrId of the company the order is against.'),
      })
      .loose()
      .optional()
      .describe('Which company the order was placed against.'),
    links: z
      .object({
        document: z
          .string()
          .optional()
          .describe(
            'URL to download the document (typically PDF). Present once `status` is `Success`.',
          ),
        data: z
          .string()
          .optional()
          .describe('URL to download the structured-data form of the document (JSON / XML).'),
      })
      .loose()
      .optional()
      .describe(
        'Download links for the completed order. Empty / absent while `status` is `Pending`.',
      ),
  })
  .loose()
  .describe("An order Kyckr has placed against a registry on the caller's behalf.");

export const KyckrOrdersPageSchema = z
  .object({
    accountId: z
      .number()
      .optional()
      .describe('Kyckr account these orders were placed under. Informational.'),
    pageNumber: z.number().int().optional().describe('Current page number (1-indexed).'),
    pageSize: z.number().int().optional().describe('Page size used by Kyckr.'),
    pageOffset: z.number().int().optional().describe('Offset into the result set.'),
    totalCount: z
      .number()
      .int()
      .optional()
      .describe('Total matching orders across all pages, when reported.'),
    orders: z.array(KyckrOrderDetailsSchema).optional().describe('Orders on this page.'),
  })
  .loose()
  .describe(
    'Paginated orders page. The orders themselves are under `orders`; the remaining fields are pagination metadata.',
  );

export const KyckrDocumentDescriptionSchema = z
  .object({
    id: z
      .string()
      .optional()
      .describe(
        'Product ID for the document. Pass to `create_document_order` as `productId` to order this specific document.',
      ),
    name: z
      .string()
      .optional()
      .describe('Human-readable document name, e.g. "Form 15 - Annual Accounts 2021/22".'),
    category: z
      .string()
      .optional()
      .describe('Document category, e.g. "Annual Accounts", "Articles of Association".'),
    documentDate: z
      .string()
      .optional()
      .describe('Date associated with the document (typically the filing date) in ISO 8601.'),
    deliveryTimeMinutes: z
      .number()
      .int()
      .optional()
      .describe(
        'Target delivery time in minutes once the document is ordered. Use to set user expectations about when polling `get_order` is likely to succeed.',
      ),
    documentFormat: z
      .array(z.enum(['application/pdf', 'application/json', 'application/zip', 'application/xml']))
      .optional()
      .describe('MIME types the ordered document will be returned in.'),
    cost: KyckrCostSchema.optional().describe(
      'Credit cost that ordering this document will incur. Show to the user before ordering.',
    ),
    documentDatapoints: z
      .object({
        companyDetails: z.boolean().optional(),
        directors: z.boolean().optional(),
        shareholders: z.boolean().optional(),
        declaredBeneficialOwners: z.boolean().optional(),
      })
      .loose()
      .optional()
      .describe(
        'Which datapoints the document covers. Use to pick the cheapest document that includes the data the user actually needs (e.g. skip a "directors-only" filing if shareholders are required).',
      ),
  })
  .loose()
  .describe(
    'A document Kyckr can order from the registry. Use the `id` as `productId` when calling `create_document_order`.',
  );
