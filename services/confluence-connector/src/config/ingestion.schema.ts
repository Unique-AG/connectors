import { z } from 'zod';
import {
  DEFAULT_ALLOWED_MIME_TYPES,
  DEFAULT_MAX_FILE_SIZE_MB,
} from '../constants/defaults.constants';
import { EnabledDisabledMode, IngestionMode } from '../constants/ingestion.constants';
import { requiredStringSchema } from '../utils/zod.util';

const IngestionModeSchema = z.enum([IngestionMode.Flat]).prefault(IngestionMode.Flat);

/**
 * The slice of the opaque pageIngestionConfig the platform requires to extract text from
 * inlined page images: imageContentExtraction must be enabled and name a visual language model.
 * Both are forwarded verbatim to the ingestion request; their presence is also what turns image
 * inlining on, so the connector never inlines images the platform cannot extract.
 */
const ImageExtractionModelSchema = z.object({
  htmlConfig: z.object({
    imageContentExtraction: z.object({
      enabled: z.literal(true),
      languageModel: requiredStringSchema,
    }),
  }),
});

// Detects only that extraction was switched on (enabled: true), regardless of the model. Used to
// tell an intentional "extraction on" apart from an absent/disabled block, so we can reject the
// broken case (on but no usable model) instead of silently skipping it.
const ImageExtractionEnabledProbe = z.object({
  htmlConfig: z.object({
    imageContentExtraction: z.object({ enabled: z.literal(true) }),
  }),
});

const AttachmentConfigSchema = z
  .object({
    mode: z
      .enum([EnabledDisabledMode.Enabled, EnabledDisabledMode.Disabled])
      .prefault(EnabledDisabledMode.Enabled)
      .describe('Whether to ingest file attachments from Confluence pages'),
    allowedMimeTypes: z
      .array(z.string().min(1))
      .prefault([...DEFAULT_ALLOWED_MIME_TYPES])
      .transform((types) => types.map((type) => type.toLowerCase()))
      .describe('MIME types to include when ingesting attachments'),
    maxFileSizeMb: z
      .number()
      .int()
      .positive()
      .prefault(DEFAULT_MAX_FILE_SIZE_MB)
      .describe('Maximum file size in megabytes for attachment ingestion'),
    imageOcr: z
      .enum([EnabledDisabledMode.Enabled, EnabledDisabledMode.Disabled])
      .prefault(EnabledDisabledMode.Enabled)
      .describe(
        'Whether to request OCR-based ingestion for image attachments (jpgReadMode = DOC_INTELLIGENCE_DEFAULT). Set to disabled to defer to the destination scope ingestion config',
      ),
  })
  .transform(({ mode, imageOcr, ...rest }) => ({
    ...rest,
    enabled: mode === EnabledDisabledMode.Enabled,
    imageOcrEnabled: imageOcr === EnabledDisabledMode.Enabled,
  }));

export const IngestionConfigSchema = z
  .object({
    ingestionMode: IngestionModeSchema.describe('Ingestion traversal mode'),
    scopeId: z.string().min(1).describe('Root scope ID for ingestion'),
    storeInternally: z
      .enum([EnabledDisabledMode.Enabled, EnabledDisabledMode.Disabled])
      .prefault(EnabledDisabledMode.Enabled)
      .transform((v) => v === EnabledDisabledMode.Enabled)
      .describe('Whether to store content internally in Unique'),
    useV1KeyFormat: z
      .enum([EnabledDisabledMode.Enabled, EnabledDisabledMode.Disabled])
      .prefault(EnabledDisabledMode.Disabled)
      .transform((v) => v === EnabledDisabledMode.Enabled)
      .describe(
        'Use v1-compatible ingestion key format (spaceId_spaceKey/pageId) without tenant prefix',
      ),
    attachments: AttachmentConfigSchema.prefault({}).describe(
      'Configuration for file attachment ingestion',
    ),
    pageIngestionConfig: z
      .record(z.string(), z.unknown())
      .optional()
      .describe(
        'Ingestion configuration applied to each ingested page. Setting htmlConfig.imageContentExtraction.enabled to true and htmlConfig.imageContentExtraction.languageModel to a visual LLM turns on inlining of page images as base64 data URIs (requires Unique platform 2026.24.0+); without both, images fall back to standalone attachment ingestion',
      ),
  })
  .superRefine((cfg, ctx) => {
    const extractionSwitchedOn = ImageExtractionEnabledProbe.safeParse(
      cfg.pageIngestionConfig,
    ).success;
    const fullyConfigured = ImageExtractionModelSchema.safeParse(cfg.pageIngestionConfig).success;

    // enabled: true but no usable languageModel would inline images the platform cannot extract,
    // silently losing their content. Reject at load instead. An absent or disabled block is fine.
    if (extractionSwitchedOn && !fullyConfigured) {
      ctx.addIssue({
        code: 'custom',
        path: ['pageIngestionConfig', 'htmlConfig', 'imageContentExtraction', 'languageModel'],
        message:
          'imageContentExtraction.enabled is true but languageModel is missing or empty; set a visual LLM or remove the imageContentExtraction block',
      });
    }
  })
  .transform((cfg) => ({
    ...cfg,
    inlineImagesEnabled: ImageExtractionModelSchema.safeParse(cfg.pageIngestionConfig).success,
  }));

export const BYTES_PER_MB = 1024 * 1024;

export type IngestionConfig = z.infer<typeof IngestionConfigSchema>;
export type AttachmentConfig = z.infer<typeof AttachmentConfigSchema>;
