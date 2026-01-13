import z from 'zod/v4';

// SECTION - GetUsers endpoint types

export const PublicGetUsersRequestSchema = z.object({
  skip: z.number().int().min(0).optional(),
  take: z.number().int().min(1).max(1000).optional(),
  email: z.string().optional(),
  userName: z.string().optional(),
  displayName: z.string().optional(),
});
export type PublicGetUsersRequest = z.infer<typeof PublicGetUsersRequestSchema>;

export const PublicUserResultSchema = z.object({
  id: z.string(),
  externalId: z.string().nullable().optional(),
  firstName: z.string().nullable().optional(),
  lastName: z.string().nullable().optional(),
  displayName: z.string().nullable().optional(),
  userName: z.string().nullable().optional(),
  email: z.email(),
  updatedAt: z.iso.datetime().optional(),
  createdAt: z.iso.datetime().optional(),
  active: z.boolean(),
  object: z.literal('user'),
});
export type PublicUserResult = z.infer<typeof PublicUserResultSchema>;

export const PublicUsersResultSchema = z.object({
  users: z.array(PublicUserResultSchema),
  object: z.literal('users'),
});
export type PublicUsersResult = z.infer<typeof PublicUsersResultSchema>;

// !SECTION - GetUsers endpoint types

// SECTION - CreateScope endpoint types

export const PublicCreateScopeRequestSchema = z.object({
  paths: z.array(z.string()),
  inheritAccess: z.boolean(),
});
export type PublicCreateScopeRequest = z.infer<typeof PublicCreateScopeRequestSchema>;

export const ScopeSchema = z.object({
  id: z.string(),
  name: z.string(),
  parentId: z.string().nullable().optional(),
  object: z.literal('folder'),
});
export type Scope = z.infer<typeof ScopeSchema>;

export const PublicCreateScopeResultSchema = z.object({
  createdFolders: z.array(ScopeSchema).default([]),
});
export type PublicCreateScopeResult = z.infer<typeof PublicCreateScopeResultSchema>;

// !SECTION - CreateScope endpoint types

// SECTION - AddScopeAccess endpoint types

export enum ScopeAccessType {
  Manage = 'MANAGE',
  Read = 'READ',
  Write = 'WRITE',
}

export enum ScopeAccessEntityType {
  Group = 'GROUP',
  User = 'USER',
}

export const PublicScopeAccessRequestSchema = z.object({
  entityId: z.string(),
  entityType: z.enum(ScopeAccessEntityType),
  type: z.enum(ScopeAccessType),
});
export type PublicScopeAccessSchema = z.infer<typeof PublicScopeAccessRequestSchema>;
export type PublicScopeAccessRequest = z.infer<typeof PublicScopeAccessRequestSchema>;

export const PublicAddScopeAccessRequestSchema = z
  .object({
    scopeId: z.string().optional(),
    scopePath: z.string().optional(),
    scopeAccesses: z.array(PublicScopeAccessRequestSchema),
    applyToSubScopes: z.boolean().default(false),
  })
  .refine((data) => data.scopeId || data.scopePath, {
    message: 'scopeId or scopePath must be provided.',
  });
export type PublicAddScopeAccessRequest = z.infer<typeof PublicAddScopeAccessRequestSchema>;

export const ChildrenScopeSchema = z.object({
  id: z.string(),
  name: z.string(),
});
export type ChildrenScope = z.infer<typeof ChildrenScopeSchema>;

export const PublicAddScopeAccessResultSchema = z.object({
  id: z.string(),
  name: z.string(),
  scopeAccesses: z.array(PublicScopeAccessRequestSchema),
  children: z.array(ChildrenScopeSchema),
  object: z.literal('updateFolderAccessResult'),
});
export type PublicAddScopeAccessResult = z.infer<typeof PublicAddScopeAccessResultSchema>;

// !SECTION - AddScopeAccess endpoint types

// SECTION - ContentUpsert endpoint types

export enum UniqueIngestionMode {
  INGESTION = 'INGESTION',
  SKIP_INGESTION = 'SKIP_INGESTION',
  SKIP_EXCEL_INGESTION = 'SKIP_EXCEL_INGESTION',
  EXTERNAL_INGESTION = 'EXTERNAL_INGESTION',
}

export const VttConfigSchema = z.object({
  languageModel: z.string().optional(),
});
export type VttConfig = z.infer<typeof VttConfigSchema>;

export const CustomApiOptionsSchema = z.object({
  apiIdentifier: z.string(),
  apiPayload: z.string().optional(),
  customisationType: z.string(),
});
export type CustomApiOptions = z.infer<typeof CustomApiOptionsSchema>;

export const IngestionConfigSchema = z.object({
  chunkMaxTokens: z.number().optional(),
  chunkMaxTokensOnePager: z.number().optional(),
  chunkMinTokens: z.number().optional(),
  chunkStrategy: z.string().optional(),
  customApiOptions: z.array(CustomApiOptionsSchema).optional(),
  documentMinTokens: z.number().optional(),
  excelReadMode: z.string().optional(),
  jpgReadMode: z.string().optional(),
  pdfReadMode: z.string().optional(),
  pptReadMode: z.string().optional(),
  uniqueIngestionMode: z.enum(UniqueIngestionMode).optional(),
  vttConfig: VttConfigSchema.optional(),
  wordReadMode: z.string().optional(),
});
export type IngestionConfig = z.infer<typeof IngestionConfigSchema>;

export const ContentUpsertInputSchema = z.object({
  key: z.string().min(1),
  title: z.string().min(1),
  description: z.string().optional(),
  mimeType: z.string().min(1),
  byteSize: z.number().optional(),
  url: z.string().optional(),
  ingestionConfig: IngestionConfigSchema.optional(),
  metadata: z.json().optional(),
});
export type ContentUpsertInput = z.infer<typeof ContentUpsertInputSchema>;

export const PublicContentUpsertRequestSchema = z.object({
  input: ContentUpsertInputSchema,
  scopeId: z.string().optional(),
  chatId: z.string().optional(),
  storeInternally: z.boolean().default(true),
  fileUrl: z.string().optional(),
});
export type PublicContentUpsertRequest = z.infer<typeof PublicContentUpsertRequestSchema>;

export const PublicContentUpsertResultSchema = z.object({
  id: z.string(),
  key: z.string(),
  url: z.string().nullable(),
  title: z.string().nullable(),
  description: z.string().nullable(),
  mimeType: z.string().nullable(),
  metadata: z.any().nullable(),
  updatedAt: z.iso.datetime().optional(),
  readUrl: z.string(),
  writeUrl: z.string(),
  object: z.literal('content'),
});
export type PublicContentUpsertResult = z.infer<typeof PublicContentUpsertResultSchema>;

// !SECTION - ContentUpsert endpoint types
