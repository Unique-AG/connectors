import { beforeEach, describe, expect, it } from 'vitest';
import { LogsDiagnosticDataPolicy } from '../config/app.config';
import { createSmeared, isSmearingActive, Smeared } from './smeared';

describe('Smeared', () => {
  describe('constructor and getters', () => {
    it('stores and retrieves the raw string value', () => {
      const smeared = new Smeared('admin@acme.com', true);

      expect(smeared.value).toBe('admin@acme.com');
    });

    it('stores and retrieves the active flag', () => {
      expect(new Smeared('test', true).active).toBe(true);
      expect(new Smeared('test', false).active).toBe(false);
    });
  });

  describe('toString() with active smearing', () => {
    it('returns smeared value when active is true', () => {
      const smeared = new Smeared('admin@acme.com', true);
      const result = smeared.toString();

      expect(result).not.toBe('admin@acme.com');
      expect(result).toContain('*');
      expect(result).toContain('.com');
    });

    it('returns raw value when active is false', () => {
      const smeared = new Smeared('admin@acme.com', false);

      expect(smeared.toString()).toBe('admin@acme.com');
    });

    it('works in string interpolation when active', () => {
      const email = new Smeared('admin@acme.com', true);
      const message = `User: ${email}`;

      expect(message).toContain('User:');
      expect(message).toContain('*');
      expect(message).not.toContain('admin@acme.com');
    });

    it('works in string interpolation when inactive', () => {
      const email = new Smeared('admin@acme.com', false);

      expect(`User: ${email}`).toBe('User: admin@acme.com');
    });
  });

  describe('toJSON() behavior', () => {
    it('delegates to toString() when active', () => {
      const smeared = new Smeared('admin@acme.com', true);

      expect(smeared.toJSON()).toBe(smeared.toString());
      expect(smeared.toJSON()).toContain('*');
    });

    it('delegates to toString() when inactive', () => {
      const smeared = new Smeared('admin@acme.com', false);

      expect(smeared.toJSON()).toBe('admin@acme.com');
    });

    it('smears in JSON.stringify when active', () => {
      const config = {
        email: new Smeared('admin@acme.com', true),
        visible: 'public-info',
      };
      const json = JSON.stringify(config);

      expect(json).toContain('*');
      expect(json).toContain('public-info');
      expect(json).not.toContain('admin@acme.com');
    });

    it('shows raw value in JSON.stringify when inactive', () => {
      const config = {
        email: new Smeared('admin@acme.com', false),
        visible: 'public-info',
      };
      const json = JSON.stringify(config);

      expect(json).toContain('admin@acme.com');
      expect(json).toContain('public-info');
    });
  });

  describe('createSmeared() factory', () => {
    beforeEach(() => {
      delete process.env.LOGS_DIAGNOSTICS_DATA_POLICY;
    });

    it('creates instance with active=true when env is CONCEAL', () => {
      process.env.LOGS_DIAGNOSTICS_DATA_POLICY = LogsDiagnosticDataPolicy.CONCEAL;

      const smeared = createSmeared('test-value');

      expect(smeared.active).toBe(true);
      expect(smeared.toString()).toContain('*');
    });

    it('creates instance with active=false when env is DISCLOSE', () => {
      process.env.LOGS_DIAGNOSTICS_DATA_POLICY = LogsDiagnosticDataPolicy.DISCLOSE;

      const smeared = createSmeared('test-value');

      expect(smeared.active).toBe(false);
      expect(smeared.toString()).toBe('test-value');
    });

    it('creates instance with active=true when env is not set', () => {
      delete process.env.LOGS_DIAGNOSTICS_DATA_POLICY;

      const smeared = createSmeared('test-value');

      expect(smeared.active).toBe(true);
      expect(smeared.toString()).toContain('*');
    });

    it('creates instance with active=true when env has invalid value', () => {
      process.env.LOGS_DIAGNOSTICS_DATA_POLICY = 'invalid-value';

      const smeared = createSmeared('test-value');

      expect(smeared.active).toBe(true);
    });
  });

  describe('isSmearingActive() helper', () => {
    beforeEach(() => {
      delete process.env.LOGS_DIAGNOSTICS_DATA_POLICY;
    });

    it('returns true when env is CONCEAL', () => {
      process.env.LOGS_DIAGNOSTICS_DATA_POLICY = LogsDiagnosticDataPolicy.CONCEAL;

      expect(isSmearingActive()).toBe(true);
    });

    it('returns false when env is DISCLOSE', () => {
      process.env.LOGS_DIAGNOSTICS_DATA_POLICY = LogsDiagnosticDataPolicy.DISCLOSE;

      expect(isSmearingActive()).toBe(false);
    });

    it('returns true when env is not set', () => {
      delete process.env.LOGS_DIAGNOSTICS_DATA_POLICY;

      expect(isSmearingActive()).toBe(true);
    });

    it('returns true when env has invalid value', () => {
      process.env.LOGS_DIAGNOSTICS_DATA_POLICY = 'invalid-value';

      expect(isSmearingActive()).toBe(true);
    });
  });

  describe('value getter always returns raw value', () => {
    it('returns raw value regardless of active flag', () => {
      const active = new Smeared('sensitive-data', true);
      const inactive = new Smeared('sensitive-data', false);

      expect(active.value).toBe('sensitive-data');
      expect(inactive.value).toBe('sensitive-data');
    });
  });
});
