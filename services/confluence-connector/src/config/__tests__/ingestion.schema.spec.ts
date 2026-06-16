import { describe, expect, it } from 'vitest';
import { IngestionConfigSchema } from '../ingestion.schema';

const validPageIngestionConfig = {
  htmlConfig: { imageContentExtraction: { enabled: true, languageModel: 'a-model' } },
};

describe('IngestionConfigSchema inlineImagesEnabled', () => {
  it('enables inlining when pageIngestionConfig carries the image extraction model', () => {
    const config = IngestionConfigSchema.parse({
      scopeId: 'root-scope',
      pageIngestionConfig: validPageIngestionConfig,
    });
    expect(config.inlineImagesEnabled).toBe(true);
  });

  it('disables inlining when pageIngestionConfig is absent', () => {
    const config = IngestionConfigSchema.parse({ scopeId: 'root-scope' });
    expect(config.inlineImagesEnabled).toBe(false);
  });

  it('disables inlining when the image extraction model is missing', () => {
    const config = IngestionConfigSchema.parse({
      scopeId: 'root-scope',
      pageIngestionConfig: { htmlConfig: { imageContentExtraction: { enabled: true } } },
    });
    expect(config.inlineImagesEnabled).toBe(false);
  });

  it('disables inlining when the image extraction model is an empty string', () => {
    const config = IngestionConfigSchema.parse({
      scopeId: 'root-scope',
      pageIngestionConfig: {
        htmlConfig: { imageContentExtraction: { enabled: true, languageModel: '   ' } },
      },
    });
    expect(config.inlineImagesEnabled).toBe(false);
  });

  it('leaves attachment flags independent of inlining', () => {
    const config = IngestionConfigSchema.parse({
      scopeId: 'root-scope',
      attachments: { imageOcr: 'enabled' },
    });
    expect(config.inlineImagesEnabled).toBe(false);
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

  it('is optional and undefined when omitted', () => {
    const config = IngestionConfigSchema.parse({ scopeId: 'root-scope' });
    expect(config.pageIngestionConfig).toBeUndefined();
  });
});
