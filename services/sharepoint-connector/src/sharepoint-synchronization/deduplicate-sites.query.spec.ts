import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Smeared } from '../utils/smeared';
import { createMockSiteConfig } from '../utils/test-utils/mock-site-config';
import { DeduplicateSitesQuery } from './deduplicate-sites.query';

describe('DeduplicateSitesQuery', () => {
  let query: DeduplicateSitesQuery;
  let loggerSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    query = new DeduplicateSitesQuery();
    loggerSpy = vi.fn();
    Object.defineProperty(query, 'logger', {
      value: {
        log: vi.fn(),
        error: loggerSpy,
        warn: vi.fn(),
        debug: vi.fn(),
        verbose: vi.fn(),
      },
      writable: true,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('deduplicateByScopeId', () => {
    it('logs an error and drops duplicates when two fixed rows share a scopeId', () => {
      const site1 = createMockSiteConfig({
        siteId: new Smeared('site-1', false),
        scopeId: { type: 'fixed', scopeId: 'scope_duplicate' },
      });
      const site2 = createMockSiteConfig({
        siteId: new Smeared('site-2', false),
        scopeId: { type: 'fixed', scopeId: 'scope_duplicate' },
      });
      const site3 = createMockSiteConfig({
        siteId: new Smeared('site-3', false),
        scopeId: { type: 'fixed', scopeId: 'scope_unique' },
      });

      const result = query.execute([site1, site2, site3]);

      expect(result).toHaveLength(2);
      expect(result[0]?.siteId.value).toBe('site-1');
      expect(result[1]?.siteId.value).toBe('site-3');
      expect(loggerSpy).toHaveBeenCalledWith(
        expect.stringContaining('DUPLICATE SCOPE ID DETECTED!'),
      );
      expect(loggerSpy).toHaveBeenCalledWith(expect.stringContaining('scope_duplicate'));
      expect(loggerSpy).toHaveBeenCalledWith(
        expect.stringContaining('siteId: site-1 (WILL SYNC - first occurrence)'),
      );
      expect(loggerSpy).toHaveBeenCalledWith(
        expect.stringContaining('siteId: site-2 (SKIPPED - duplicate scopeId)'),
      );
    });

    it('does not log a duplicate-scope error when every fixed scopeId is unique', () => {
      const site1 = createMockSiteConfig({
        siteId: new Smeared('site-1', false),
        scopeId: { type: 'fixed', scopeId: 'scope_a' },
      });
      const site2 = createMockSiteConfig({
        siteId: new Smeared('site-2', false),
        scopeId: { type: 'fixed', scopeId: 'scope_b' },
      });

      query.execute([site1, site2]);

      expect(loggerSpy).not.toHaveBeenCalledWith(
        expect.stringContaining('DUPLICATE SCOPE ID DETECTED!'),
      );
    });

    it('passes auto rows through alongside fixed rows', () => {
      const autoSite = createMockSiteConfig({
        siteId: new Smeared('site-auto', false),
        scopeId: { type: 'auto', parentScopeId: 'scope_X' },
      });
      const fixedSite = createMockSiteConfig({
        siteId: new Smeared('site-fixed', false),
        scopeId: { type: 'fixed', scopeId: 'scope_Y' },
      });

      const result = query.execute([autoSite, fixedSite]);

      expect(result).toEqual([autoSite, fixedSite]);
    });

    it('does not collapse auto rows that share a parentScopeId', () => {
      const autoSiteA = createMockSiteConfig({
        siteId: new Smeared('site-auto-a', false),
        scopeId: { type: 'auto', parentScopeId: 'scope_P' },
      });
      const autoSiteB = createMockSiteConfig({
        siteId: new Smeared('site-auto-b', false),
        scopeId: { type: 'auto', parentScopeId: 'scope_P' },
      });

      const result = query.execute([autoSiteA, autoSiteB]);

      expect(result).toEqual([autoSiteA, autoSiteB]);
    });
  });

  describe('deduplicateBySiteId', () => {
    it('keeps only the first occurrence when two fixed rows share a siteId', () => {
      const dup = new Smeared('dup-site', false);
      const site1 = createMockSiteConfig({
        siteId: dup,
        scopeId: { type: 'fixed', scopeId: 'scope_first' },
      });
      const site2 = createMockSiteConfig({
        siteId: dup,
        scopeId: { type: 'fixed', scopeId: 'scope_second' },
      });

      const result = query.execute([site1, site2]);

      expect(result).toHaveLength(1);
      expect(result[0]).toBe(site1);
      expect(loggerSpy).toHaveBeenCalledWith(
        expect.stringContaining('DUPLICATE SITE ID DETECTED!'),
      );
      expect(loggerSpy).toHaveBeenCalledWith(expect.stringContaining('dup-site'));
    });

    it('keeps the fixed row when fixed appears before auto with the same siteId', () => {
      const dup = new Smeared('dup-site', false);
      const fixedSite = createMockSiteConfig({
        siteId: dup,
        scopeId: { type: 'fixed', scopeId: 'scope_fixed' },
      });
      const autoSite = createMockSiteConfig({
        siteId: dup,
        scopeId: { type: 'auto', parentScopeId: 'scope_parent' },
      });

      const result = query.execute([fixedSite, autoSite]);

      expect(result).toHaveLength(1);
      expect(result[0]).toBe(fixedSite);
      expect(loggerSpy).toHaveBeenCalledWith(
        expect.stringContaining('DUPLICATE SITE ID DETECTED!'),
      );
    });

    it('keeps the auto row when auto appears before fixed with the same siteId', () => {
      const dup = new Smeared('dup-site', false);
      const autoSite = createMockSiteConfig({
        siteId: dup,
        scopeId: { type: 'auto', parentScopeId: 'scope_parent' },
      });
      const fixedSite = createMockSiteConfig({
        siteId: dup,
        scopeId: { type: 'fixed', scopeId: 'scope_fixed' },
      });

      const result = query.execute([autoSite, fixedSite]);

      expect(result).toHaveLength(1);
      expect(result[0]).toBe(autoSite);
      expect(loggerSpy).toHaveBeenCalledWith(
        expect.stringContaining('DUPLICATE SITE ID DETECTED!'),
      );
    });

    it('keeps only the first occurrence when two auto rows share a siteId', () => {
      const dup = new Smeared('dup-site', false);
      const auto1 = createMockSiteConfig({
        siteId: dup,
        scopeId: { type: 'auto', parentScopeId: 'scope_p1' },
      });
      const auto2 = createMockSiteConfig({
        siteId: dup,
        scopeId: { type: 'auto', parentScopeId: 'scope_p2' },
      });

      const result = query.execute([auto1, auto2]);

      expect(result).toHaveLength(1);
      expect(result[0]).toBe(auto1);
      expect(loggerSpy).toHaveBeenCalledWith(
        expect.stringContaining('DUPLICATE SITE ID DETECTED!'),
      );
    });

    it('keeps both auto rows that share a parent but have different siteIds', () => {
      const autoA = createMockSiteConfig({
        siteId: new Smeared('site-a', false),
        scopeId: { type: 'auto', parentScopeId: 'scope_shared' },
      });
      const autoB = createMockSiteConfig({
        siteId: new Smeared('site-b', false),
        scopeId: { type: 'auto', parentScopeId: 'scope_shared' },
      });

      const result = query.execute([autoA, autoB]);

      expect(result).toEqual([autoA, autoB]);
    });
  });
});
