import { describe, expect, it } from 'vitest';
import { IngestionConfigSchema } from '../ingestion.schema';

const validPageIngestionConfig = {
  htmlConfig: { imageContentExtraction: { enabled: true, languageModel: 'a-model' } },
};

describe('IngestionConfigSchema attachments.inlineImages', () => {
  // inlineImages defaults to enabled, which requires a pageIngestionConfig carrying the model.
  const baseInput = { scopeId: 'root-scope', pageIngestionConfig: validPageIngestionConfig };

  it('defaults inlineImagesEnabled to true when omitted', () => {
    const config = IngestionConfigSchema.parse(baseInput);
    expect(config.attachments.inlineImagesEnabled).toBe(true);
  });

  it('maps inlineImages: disabled to inlineImagesEnabled false', () => {
    const config = IngestionConfigSchema.parse({
      ...baseInput,
      attachments: { inlineImages: 'disabled' },
    });
    expect(config.attachments.inlineImagesEnabled).toBe(false);
  });

  it('maps inlineImages: enabled to inlineImagesEnabled true', () => {
    const config = IngestionConfigSchema.parse({
      ...baseInput,
      attachments: { inlineImages: 'enabled' },
    });
    expect(config.attachments.inlineImagesEnabled).toBe(true);
  });

  it('leaves the other attachment flags independent of inlineImages', () => {
    const config = IngestionConfigSchema.parse({
      ...baseInput,
      attachments: { inlineImages: 'disabled', imageOcr: 'enabled' },
    });
    expect(config.attachments.inlineImagesEnabled).toBe(false);
    expect(config.attachments.imageOcrEnabled).toBe(true);
  });
});

describe('IngestionConfigSchema pageIngestionConfig', () => {
  it('is forwarded verbatim as an opaque object', () => {
    const config = IngestionConfigSchema.parse({
      scopeId: 'root-scope',
      pageIngestionConfig: validPageIngestionConfig,
    });
    expect(config.pageIngestionConfig).toEqual(validPageIngestionConfig);
  });

  it('is optional and undefined when inlineImages is disabled', () => {
    const config = IngestionConfigSchema.parse({
      scopeId: 'root-scope',
      attachments: { inlineImages: 'disabled' },
    });
    expect(config.pageIngestionConfig).toBeUndefined();
  });
});

describe('IngestionConfigSchema image extraction model validation', () => {
  const baseInput = { scopeId: 'root-scope' };

  it('requires the model when inlineImages is enabled (default) and the config is absent', () => {
    expect(() => IngestionConfigSchema.parse(baseInput)).toThrow(
      /languageModel must be a non-empty string when attachments.inlineImages is enabled/,
    );
  });

  it('rejects a pageIngestionConfig missing the model when inlineImages is enabled', () => {
    expect(() =>
      IngestionConfigSchema.parse({
        ...baseInput,
        pageIngestionConfig: { htmlConfig: { imageContentExtraction: { enabled: true } } },
      }),
    ).toThrow(/languageModel/);
  });

  it('rejects an empty model when inlineImages is enabled', () => {
    expect(() =>
      IngestionConfigSchema.parse({
        ...baseInput,
        pageIngestionConfig: {
          htmlConfig: { imageContentExtraction: { enabled: true, languageModel: '   ' } },
        },
      }),
    ).toThrow(/languageModel/);
  });

  it('accepts a valid model when inlineImages is enabled', () => {
    const config = IngestionConfigSchema.parse({
      ...baseInput,
      pageIngestionConfig: validPageIngestionConfig,
    });
    expect(config.attachments.inlineImagesEnabled).toBe(true);
  });

  it('does not require the model when inlineImages is disabled', () => {
    const config = IngestionConfigSchema.parse({
      ...baseInput,
      attachments: { inlineImages: 'disabled' },
    });
    expect(config.pageIngestionConfig).toBeUndefined();
  });
});
