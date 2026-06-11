import { describe, expect, it } from 'vitest';
import { IngestionConfigSchema } from '../ingestion.schema';

describe('IngestionConfigSchema attachments.inlineImages', () => {
  const baseInput = { scopeId: 'root-scope' };

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
