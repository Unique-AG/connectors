import { beforeEach, describe, expect, it } from 'vitest';
import {
  LOGS_DIAGNOSTICS_DATA_POLICY_ENV_NAME,
  LogsDiagnosticDataPolicy,
} from '../config/app.config';
import { createSmeared, isSmearingActiveFromEnv, Smeared } from './smeared';

describe('Smeared', () => {
  describe('constructor and getters', () => {
    it('stores and retrieves the raw string value', () => {
      const value = 'bd9c85ee-998f-4665-9c44-577cf5a08a66';
      const smeared = new Smeared(value, true);

      expect(smeared.value).toBe(value);
    });

    it('stores and retrieves the active flag', () => {
      const smeared = new Smeared('test-value', true);
      expect(smeared.active).toBe(true);

      const smearedInactive = new Smeared('test-value', false);
      expect(smearedInactive.active).toBe(false);
    });
  });

  describe('toString() with active smearing', () => {
    it('returns smeared value when active is true', () => {
      const value = 'bd9c85ee-998f-4665-9c44-577cf5a08a66';
      const smeared = new Smeared(value, true);

      const result = smeared.toString();

      expect(result).not.toBe(value);
      expect(result).toContain('8a66'); // Last 4 chars visible
      expect(result).toContain('*'); // Contains asterisks
    });

    it('returns raw value when active is false', () => {
      const value = 'bd9c85ee-998f-4665-9c44-577cf5a08a66';
      const smeared = new Smeared(value, false);

      const result = smeared.toString();

      expect(result).toBe(value);
      expect(result).not.toContain('*');
    });

    it('works in string interpolation when active', () => {
      const siteId = new Smeared('bd9c85ee-998f-4665-9c44', true);
      const message = `Processing site: ${siteId}`;

      expect(message).toContain('Processing site:');
      expect(message).toContain('*');
      expect(message).not.toContain('bd9c85ee-998f-4665-9c44');
    });

    it('works in string interpolation when inactive', () => {
      const siteId = new Smeared('bd9c85ee-998f-4665-9c44', false);
      const message = `Processing site: ${siteId}`;

      expect(message).toBe('Processing site: bd9c85ee-998f-4665-9c44');
    });
  });

  describe('toJSON() behavior', () => {
    it('delegates to toString() when active', () => {
      const value = 'bd9c85ee-998f-4665-9c44-577cf5a08a66';
      const smeared = new Smeared(value, true);

      expect(smeared.toJSON()).toBe(smeared.toString());
      expect(smeared.toJSON()).toContain('*');
    });

    it('delegates to toString() when inactive', () => {
      const value = 'bd9c85ee-998f-4665-9c44-577cf5a08a66';
      const smeared = new Smeared(value, false);

      expect(smeared.toJSON()).toBe(smeared.toString());
      expect(smeared.toJSON()).toBe(value);
    });

    it('smears in JSON.stringify when active', () => {
      const config = {
        siteId: new Smeared('bd9c85ee-998f-4665-9c44', true),
        otherData: 'visible',
      };

      const json = JSON.stringify(config);

      expect(json).toContain('*');
      expect(json).toContain('visible');
      expect(json).not.toContain('bd9c85ee-998f-4665-9c44');
    });

    it('shows raw value in JSON.stringify when inactive', () => {
      const config = {
        siteId: new Smeared('bd9c85ee-998f-4665-9c44', false),
        otherData: 'visible',
      };

      const json = JSON.stringify(config);

      expect(json).toContain('bd9c85ee-998f-4665-9c44');
      expect(json).toContain('visible');
    });
  });

  describe('createSmeared() factory', () => {
    beforeEach(() => {
      // Reset environment variable before each test
      delete process.env[LOGS_DIAGNOSTICS_DATA_POLICY_ENV_NAME];
    });

    it('creates instance with active=true when env is CONCEAL', () => {
      process.env[LOGS_DIAGNOSTICS_DATA_POLICY_ENV_NAME] = LogsDiagnosticDataPolicy.CONCEAL;

      const smeared = createSmeared('test-value');

      expect(smeared.active).toBe(true);
      expect(smeared.toString()).toContain('*');
    });

    it('creates instance with active=false when env is DISCLOSE', () => {
      process.env[LOGS_DIAGNOSTICS_DATA_POLICY_ENV_NAME] = LogsDiagnosticDataPolicy.DISCLOSE;

      const smeared = createSmeared('test-value');

      expect(smeared.active).toBe(false);
      expect(smeared.toString()).toBe('test-value');
    });

    it('creates instance with active=true when env is not set', () => {
      delete process.env[LOGS_DIAGNOSTICS_DATA_POLICY_ENV_NAME];

      const smeared = createSmeared('test-value');

      expect(smeared.active).toBe(true);
      expect(smeared.toString()).toContain('*');
    });

    it('creates instance with active=true when env is invalid value', () => {
      process.env[LOGS_DIAGNOSTICS_DATA_POLICY_ENV_NAME] = 'invalid-value';

      const smeared = createSmeared('test-value');

      expect(smeared.active).toBe(true);
    });
  });

  describe('isSmearingActiveFromEnv() helper', () => {
    beforeEach(() => {
      delete process.env[LOGS_DIAGNOSTICS_DATA_POLICY_ENV_NAME];
    });

    it('returns true when env is CONCEAL', () => {
      process.env[LOGS_DIAGNOSTICS_DATA_POLICY_ENV_NAME] = LogsDiagnosticDataPolicy.CONCEAL;

      expect(isSmearingActiveFromEnv()).toBe(true);
    });

    it('returns false when env is DISCLOSE', () => {
      process.env[LOGS_DIAGNOSTICS_DATA_POLICY_ENV_NAME] = LogsDiagnosticDataPolicy.DISCLOSE;

      expect(isSmearingActiveFromEnv()).toBe(false);
    });

    it('returns true when env is not set', () => {
      delete process.env[LOGS_DIAGNOSTICS_DATA_POLICY_ENV_NAME];

      expect(isSmearingActiveFromEnv()).toBe(true);
    });

    it('returns true when env is invalid value', () => {
      process.env[LOGS_DIAGNOSTICS_DATA_POLICY_ENV_NAME] = 'invalid-value';

      expect(isSmearingActiveFromEnv()).toBe(true);
    });
  });

  describe('integration tests', () => {
    it('prevents accidental logging of PII in production mode', () => {
      process.env[LOGS_DIAGNOSTICS_DATA_POLICY_ENV_NAME] = LogsDiagnosticDataPolicy.CONCEAL;

      const siteId = createSmeared('bd9c85ee-998f-4665-9c44-577cf5a08a66');
      const logMessage = `Processing site ${siteId}`;

      expect(logMessage).toContain('*');
      expect(logMessage).not.toContain('bd9c85ee-998f-4665-9c44-577cf5a08a66');
    });

    it('allows debugging with raw values in development mode', () => {
      process.env[LOGS_DIAGNOSTICS_DATA_POLICY_ENV_NAME] = LogsDiagnosticDataPolicy.DISCLOSE;

      const siteId = createSmeared('bd9c85ee-998f-4665-9c44-577cf5a08a66');
      const logMessage = `Processing site ${siteId}`;

      expect(logMessage).toBe('Processing site bd9c85ee-998f-4665-9c44-577cf5a08a66');
    });

    it('works with nested objects in structured logging', () => {
      process.env[LOGS_DIAGNOSTICS_DATA_POLICY_ENV_NAME] = LogsDiagnosticDataPolicy.CONCEAL;

      const context = {
        siteId: createSmeared('bd9c85ee-998f-4665-9c44'),
        path: createSmeared('/sites/mysite/documents'),
        visibleData: 'public-info',
      };

      const json = JSON.stringify(context);

      expect(json).toContain('*');
      expect(json).toContain('public-info');
      expect(json).not.toContain('bd9c85ee-998f-4665-9c44');
      expect(json).not.toContain('/sites/mysite/documents');
    });

    it('value getter always returns raw value regardless of active flag', () => {
      const activeSmeared = new Smeared('sensitive-data', true);
      const inactiveSmeared = new Smeared('sensitive-data', false);

      expect(activeSmeared.value).toBe('sensitive-data');
      expect(inactiveSmeared.value).toBe('sensitive-data');
    });
  });
});
