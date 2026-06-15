import * as z from 'zod';

// Schemas mirroring the JSON form of an ordered registry document, served by
// `GET /orders/{orderId}/download?format=json`. Field names use PascalCase
// because that is what Kyckr emits on this endpoint (the rest of the v2 API
// is camelCase). All schemas are `.loose()` so jurisdiction-specific extras
// still reach the LLM, and most fields are `.nullish()` because registry
// coverage varies.

const KyckrOrderDocumentNormalizedValueSchema = z
  .object({
    Original: z
      .string()
      .nullish()
      .describe('Value as provided by the source registry, in the registry-specific format.'),
    Normalized: z
      .union([z.string(), z.number()])
      .nullish()
      .describe(
        'Kyckr-normalized form. Type is `string` for most fields (e.g. ISO date `YYYY-MM-DD`, controlled vocabulary entries) and `number` for some enumerations (e.g. `Status.Normalized` returns an integer code).',
      ),
  })
  .loose()
  .describe('A registry value reported with both an original (source) form and a normalized form.');

const KyckrOrderDocumentAddressSchema = z
  .object({
    Type: z
      .string()
      .nullish()
      .describe('Address role, e.g. "POSTAL", "OFFICE", "REGISTERED", "DELIVERY", "INVOICE".'),
    FullAddress: z
      .string()
      .nullish()
      .describe('Address as a single human-readable string. Best field to display to the user.'),
    RawAddressLines: z.array(z.string()).nullish(),
    BuildingName: z.string().nullish(),
    StreetNumber: z.string().nullish(),
    StreetName: z.string().nullish(),
    City: z.string().nullish(),
    Postcode: z.string().nullish(),
    Municipality: z.string().nullish(),
    Region: z.string().nullish(),
    Country: z
      .string()
      .nullish()
      .describe('Country in registry-supplied form. May be ISO alpha-2 (e.g. "GB") or full name.'),
    SecondaryPostalCode: z.string().nullish(),
  })
  .loose()
  .describe('Standardized address. `FullAddress` is the safest field to display.');

const KyckrOrderDocumentPartySchema = z
  .object({
    Type: z
      .union([z.number(), z.string()])
      .nullish()
      .describe('Party kind, typically `0` for natural person and `1` for corporation.'),
    IdNumber: z.string().nullish(),
    Name: z.string().nullish(),
    Address: KyckrOrderDocumentAddressSchema.nullish(),
    RegistrationNumber: z
      .string()
      .nullish()
      .describe('Set when the party is itself a registered corporation.'),
    RegistrationDate: KyckrOrderDocumentNormalizedValueSchema.nullish(),
    RegistrationAuthority: z.string().nullish(),
    RegisteredAddress: KyckrOrderDocumentAddressSchema.nullish(),
  })
  .loose()
  .describe(
    'A natural person or corporation appearing on the document (shareholder, director, etc.).',
  );

const KyckrOrderDocumentRepresentativeSchema = z
  .object({
    Role: KyckrOrderDocumentNormalizedValueSchema.nullish(),
    StartDate: KyckrOrderDocumentNormalizedValueSchema.nullish(),
    EndDate: KyckrOrderDocumentNormalizedValueSchema.nullish(),
    IsActive: z.boolean().nullish(),
    Directorships: z.array(z.unknown()).nullish(),
    Powers: z.array(z.unknown()).nullish(),
    Birthdate: KyckrOrderDocumentNormalizedValueSchema.nullish(),
    Nationality: z.string().nullish(),
    PlaceOfBirth: z.string().nullish(),
    PlaceOfResidence: z.string().nullish(),
    Type: z.union([z.number(), z.string()]).nullish(),
    IdNumber: z.string().nullish(),
    Name: z.string().nullish(),
    Address: KyckrOrderDocumentAddressSchema.nullish(),
  })
  .loose()
  .describe('A representative (typically a director) listed on the document.');

const KyckrOrderDocumentRepresentativesSchema = z
  .object({
    Corporations: z.array(KyckrOrderDocumentRepresentativeSchema).nullish(),
    Individuals: z.array(KyckrOrderDocumentRepresentativeSchema).nullish(),
  })
  .loose();

const KyckrOrderDocumentShareholdersSchema = z
  .object({
    Corporations: z.array(KyckrOrderDocumentPartySchema).nullish(),
    Individuals: z.array(KyckrOrderDocumentPartySchema).nullish(),
  })
  .loose();

const KyckrOrderDocumentShareholdingSchema = z
  .object({
    Percentage: z
      .string()
      .nullish()
      .describe('Percentage of the share class held, as a string (e.g. "100.0").'),
    Count: z.union([z.number(), z.string()]).nullish(),
    TotalNominalValue: z.number().nullish(),
    Shareholders: KyckrOrderDocumentShareholdersSchema.nullish(),
  })
  .loose();

const KyckrOrderDocumentCapitalSchema = z
  .object({
    Type: z.string().nullish(),
    Description: z.string().nullish(),
    ClassCode: z.string().nullish(),
    ClassDescription: z.string().nullish(),
    Quantity: z.number().nullish(),
    UnitNominalValue: z.number().nullish(),
    TotalNominalValue: z.number().nullish(),
    Currency: z.string().nullish(),
    Shareholdings: z.array(KyckrOrderDocumentShareholdingSchema).nullish(),
  })
  .loose()
  .describe("An entry from the company's capital structure.");

const KyckrOrderDocumentContactDetailsSchema = z
  .object({
    Email: z.string().nullish(),
    Fax: z.string().nullish(),
    TelNumber: z.string().nullish(),
    Website: z.string().nullish(),
  })
  .loose();

const KyckrOrderDocumentIdentifiersSchema = z
  .object({
    PrimaryRegistrationNumber: z.string().nullish(),
    TaxNumber: z.string().nullish(),
    SecondaryRegistrationNumber: z.string().nullish(),
  })
  .loose();

const KyckrOrderDocumentAliasSchema = z
  .object({
    Name: z.string().nullish(),
    Type: z.string().nullish(),
  })
  .loose();

const KyckrOrderDocumentPreviousNameSchema = z
  .object({
    Name: z.string().nullish(),
    StartDate: KyckrOrderDocumentNormalizedValueSchema.nullish(),
    EndDate: KyckrOrderDocumentNormalizedValueSchema.nullish(),
  })
  .loose();

const KyckrOrderDocumentActivitySchema = z
  .object({
    Code: z.string().nullish(),
    Description: z.string().nullish(),
    ClassificationScheme: z.string().nullish(),
    Type: z.string().nullish(),
  })
  .loose();

export const KyckrOrderDocumentSchema = z
  .object({
    Activities: z.array(KyckrOrderDocumentActivitySchema).nullish(),
    Addresses: z.array(KyckrOrderDocumentAddressSchema).nullish(),
    Capital: z.array(KyckrOrderDocumentCapitalSchema).nullish(),
    Representatives: KyckrOrderDocumentRepresentativesSchema.nullish(),
    UltimateBeneficialOwners: z.array(z.unknown()).nullish(),
    ContactDetails: KyckrOrderDocumentContactDetailsSchema.nullish(),
    Identifiers: KyckrOrderDocumentIdentifiersSchema.nullish(),
    CompanyName: z.string().nullish(),
    TradingName: z.string().nullish(),
    EnglishName: z.string().nullish(),
    Aliases: z.array(KyckrOrderDocumentAliasSchema).nullish(),
    PreviousNames: z.array(KyckrOrderDocumentPreviousNameSchema).nullish(),
    RegistrationAuthority: z.string().nullish(),
    LastUpdated: z.string().nullish(),
    FoundationDate: KyckrOrderDocumentNormalizedValueSchema.nullish(),
    RegistrationDate: KyckrOrderDocumentNormalizedValueSchema.nullish(),
    IncorporationDate: KyckrOrderDocumentNormalizedValueSchema.nullish(),
    DissolutionDate: KyckrOrderDocumentNormalizedValueSchema.nullish(),
    Status: KyckrOrderDocumentNormalizedValueSchema.nullish(),
    LegalForm: KyckrOrderDocumentNormalizedValueSchema.nullish(),
  })
  .loose()
  .describe(
    'Structured JSON form of an ordered registry document. Field names use PascalCase (Kyckr download-endpoint convention, distinct from the rest of the v2 API). Most fields are nullable per registry coverage; jurisdiction-specific extras pass through unchanged.',
  );

export type KyckrOrderDocument = z.infer<typeof KyckrOrderDocumentSchema>;

// Envelope returned by `GET /orders/{orderId}/download?format=json`. Only
// `Data` is surfaced upstream; the wrapper fields duplicate what the parent
// order response already carries.
export const KyckrOrderDownloadEnvelopeSchema = z
  .object({
    CorrelationId: z.string().nullish(),
    CustomerReference: z.string().nullish(),
    TimeStamp: z.string().nullish(),
    Details: z.string().nullish(),
    Balances: z.unknown().nullish(),
    Links: z.unknown().nullish(),
    Data: KyckrOrderDocumentSchema.nullish(),
  })
  .loose();
