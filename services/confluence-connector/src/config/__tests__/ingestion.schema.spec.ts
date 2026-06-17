import { describe, expect, it } from 'vitest';
import {
  DEFAULT_ALLOWED_MIME_TYPES,
  DEFAULT_MAX_FILE_SIZE_MB,
} from '../../constants/defaults.constants';
import { IngestionConfigSchema } from '../ingestion.schema';

const REQUIRED_FIELDS = {
  scopeId: 'scope-abc',
};

const validPageIngestionConfig = {
  htmlConfig: { imageContentExtraction: { enabled: true, languageModel: 'a-model' } },
};

describe('IngestionConfigSchema', () => {
  describe('defaults', () => {
    it('applies enabled default to storeInternally', () => {
      const result = IngestionConfigSchema.parse(REQUIRED_FIELDS);

      expect(result.storeInternally).toBe(true);
    });

    it('applies disabled default to useV1KeyFormat', () => {
      const result = IngestionConfigSchema.parse(REQUIRED_FIELDS);

      expect(result.useV1KeyFormat).toBe(false);
    });

    it('applies default attachment configuration', () => {
      const result = IngestionConfigSchema.parse(REQUIRED_FIELDS);

      expect(result.attachments.enabled).toBe(true);
      expect(result.attachments.imageOcrEnabled).toBe(true);
      expect(result.attachments.maxFileSizeMb).toBe(DEFAULT_MAX_FILE_SIZE_MB);
      expect(result.attachments.allowedMimeTypes).toEqual([...DEFAULT_ALLOWED_MIME_TYPES]);
    });
  });

  describe('storeInternally', () => {
    it('parses "enabled" to true', () => {
      const result = IngestionConfigSchema.parse({
        ...REQUIRED_FIELDS,
        storeInternally: 'enabled',
      });

      expect(result.storeInternally).toBe(true);
    });

    it('parses "disabled" to false', () => {
      const result = IngestionConfigSchema.parse({
        ...REQUIRED_FIELDS,
        storeInternally: 'disabled',
      });

      expect(result.storeInternally).toBe(false);
    });
  });

  describe('useV1KeyFormat', () => {
    it('parses "enabled" to true', () => {
      const result = IngestionConfigSchema.parse({
        ...REQUIRED_FIELDS,
        useV1KeyFormat: 'enabled',
      });

      expect(result.useV1KeyFormat).toBe(true);
    });
  });

  describe('attachments', () => {
    it('parses "disabled" mode to enabled=false', () => {
      const result = IngestionConfigSchema.parse({
        ...REQUIRED_FIELDS,
        attachments: { mode: 'disabled' },
      });

      expect(result.attachments.enabled).toBe(false);
    });

    it('lowercases MIME types', () => {
      const result = IngestionConfigSchema.parse({
        ...REQUIRED_FIELDS,
        attachments: { allowedMimeTypes: ['Application/PDF', 'TEXT/PLAIN'] },
      });

      expect(result.attachments.allowedMimeTypes).toEqual(['application/pdf', 'text/plain']);
    });

    it('parses imageOcr "disabled" to imageOcrEnabled=false', () => {
      const result = IngestionConfigSchema.parse({
        ...REQUIRED_FIELDS,
        attachments: { imageOcr: 'disabled' },
      });

      expect(result.attachments.imageOcrEnabled).toBe(false);
    });

    it('accepts a custom maxFileSizeMb', () => {
      const result = IngestionConfigSchema.parse({
        ...REQUIRED_FIELDS,
        attachments: { maxFileSizeMb: 50 },
      });

      expect(result.attachments.maxFileSizeMb).toBe(50);
    });
  });

  describe('validation failures', () => {
    it('rejects when scopeId is missing', () => {
      expect(() => IngestionConfigSchema.parse({})).toThrow();
    });

    it('rejects when scopeId is an empty string', () => {
      expect(() => IngestionConfigSchema.parse({ scopeId: '' })).toThrow();
    });

    it('rejects a non-positive maxFileSizeMb', () => {
      expect(() =>
        IngestionConfigSchema.parse({ ...REQUIRED_FIELDS, attachments: { maxFileSizeMb: 0 } }),
      ).toThrow();
    });
  });
});

describe('IngestionConfigSchema inlineImagesEnabled', () => {
  it('enables inlining when pageIngestionConfig carries the image extraction model', () => {
    const config = IngestionConfigSchema.parse({
      ...REQUIRED_FIELDS,
      pageIngestionConfig: validPageIngestionConfig,
    });
    expect(config.inlineImagesEnabled).toBe(true);
  });

  it('disables inlining when pageIngestionConfig is absent', () => {
    const config = IngestionConfigSchema.parse(REQUIRED_FIELDS);
    expect(config.inlineImagesEnabled).toBe(false);
  });

  it('disables inlining when the image extraction model is missing', () => {
    const config = IngestionConfigSchema.parse({
      ...REQUIRED_FIELDS,
      pageIngestionConfig: { htmlConfig: { imageContentExtraction: { enabled: true } } },
    });
    expect(config.inlineImagesEnabled).toBe(false);
  });

  it('disables inlining when the image extraction model is an empty string', () => {
    const config = IngestionConfigSchema.parse({
      ...REQUIRED_FIELDS,
      pageIngestionConfig: {
        htmlConfig: { imageContentExtraction: { enabled: true, languageModel: '   ' } },
      },
    });
    expect(config.inlineImagesEnabled).toBe(false);
  });

  it('disables inlining when imageContentExtraction.enabled is missing', () => {
    const config = IngestionConfigSchema.parse({
      ...REQUIRED_FIELDS,
      pageIngestionConfig: { htmlConfig: { imageContentExtraction: { languageModel: 'a-model' } } },
    });
    expect(config.inlineImagesEnabled).toBe(false);
  });

  it('disables inlining when imageContentExtraction.enabled is false', () => {
    const config = IngestionConfigSchema.parse({
      ...REQUIRED_FIELDS,
      pageIngestionConfig: {
        htmlConfig: { imageContentExtraction: { enabled: false, languageModel: 'a-model' } },
      },
    });
    expect(config.inlineImagesEnabled).toBe(false);
  });

  it('leaves attachment flags independent of inlining', () => {
    const config = IngestionConfigSchema.parse({
      ...REQUIRED_FIELDS,
      attachments: { imageOcr: 'enabled' },
    });
    expect(config.inlineImagesEnabled).toBe(false);
    expect(config.attachments.imageOcrEnabled).toBe(true);
  });
});

describe('IngestionConfigSchema pageIngestionConfig', () => {
  it('is forwarded verbatim as an opaque object', () => {
    const config = IngestionConfigSchema.parse({
      ...REQUIRED_FIELDS,
      pageIngestionConfig: validPageIngestionConfig,
    });
    expect(config.pageIngestionConfig).toEqual(validPageIngestionConfig);
  });

  it('is optional and undefined when omitted', () => {
    const config = IngestionConfigSchema.parse(REQUIRED_FIELDS);
    expect(config.pageIngestionConfig).toBeUndefined();
  });
});
