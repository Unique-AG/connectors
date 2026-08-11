import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  assertAtLeastOneCapabilityEnabled,
  isChatEnabled,
  isIngestionEnabled,
} from './capabilities';

describe('capabilities', () => {
  const originalChat = process.env.CHAT_INTEGRATION;
  const originalUnique = process.env.UNIQUE_INTEGRATION;

  beforeEach(() => {
    delete process.env.CHAT_INTEGRATION;
    delete process.env.UNIQUE_INTEGRATION;
  });

  afterEach(() => {
    if (originalChat === undefined) {
      delete process.env.CHAT_INTEGRATION;
    } else {
      process.env.CHAT_INTEGRATION = originalChat;
    }
    if (originalUnique === undefined) {
      delete process.env.UNIQUE_INTEGRATION;
    } else {
      process.env.UNIQUE_INTEGRATION = originalUnique;
    }
  });

  describe(isChatEnabled.name, () => {
    it('defaults to enabled when CHAT_INTEGRATION is unset', () => {
      expect(isChatEnabled()).toBe(true);
    });

    it('is enabled when CHAT_INTEGRATION=enabled', () => {
      process.env.CHAT_INTEGRATION = 'enabled';
      expect(isChatEnabled()).toBe(true);
    });

    it('is disabled only when CHAT_INTEGRATION=disabled', () => {
      process.env.CHAT_INTEGRATION = 'disabled';
      expect(isChatEnabled()).toBe(false);
    });
  });

  describe(isIngestionEnabled.name, () => {
    it('defaults to disabled when UNIQUE_INTEGRATION is unset', () => {
      expect(isIngestionEnabled()).toBe(false);
    });

    it('is enabled only when UNIQUE_INTEGRATION=enabled', () => {
      process.env.UNIQUE_INTEGRATION = 'enabled';
      expect(isIngestionEnabled()).toBe(true);
    });

    it('is disabled when UNIQUE_INTEGRATION=disabled', () => {
      process.env.UNIQUE_INTEGRATION = 'disabled';
      expect(isIngestionEnabled()).toBe(false);
    });
  });

  describe(assertAtLeastOneCapabilityEnabled.name, () => {
    it('passes with defaults (chat on, ingestion off)', () => {
      expect(() => assertAtLeastOneCapabilityEnabled()).not.toThrow();
    });

    it('passes for ingestion-only (chat off, ingestion on)', () => {
      process.env.CHAT_INTEGRATION = 'disabled';
      process.env.UNIQUE_INTEGRATION = 'enabled';
      expect(() => assertAtLeastOneCapabilityEnabled()).not.toThrow();
    });

    it('throws when both capabilities are disabled', () => {
      process.env.CHAT_INTEGRATION = 'disabled';
      process.env.UNIQUE_INTEGRATION = 'disabled';
      expect(() => assertAtLeastOneCapabilityEnabled()).toThrow();
    });
  });
});
