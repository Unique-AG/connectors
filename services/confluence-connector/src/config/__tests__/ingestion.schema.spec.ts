import { describe, expect, it } from 'vitest';
import {
  DEFAULT_ALLOWED_MIME_TYPES,
  DEFAULT_MAX_FILE_SIZE_MB,
} from '../../constants/defaults.constants';
import { IngestionConfigSchema } from '../ingestion.schema';

const REQUIRED_FIELDS = {
  scopeId: 'scope-abc',
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
