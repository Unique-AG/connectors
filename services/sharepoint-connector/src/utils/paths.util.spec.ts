import { describe, expect, it } from 'vitest';
import {
  encodeSiteNameForPath,
  extractSiteNameFromWebUrl,
  isAncestorOfRootPath,
  normalizeSlashes,
} from './paths.util';

describe('normalizeSlashes', () => {
  it('removes leading and trailing whitespace', () => {
    expect(normalizeSlashes('  /path/to/file  ')).toBe('path/to/file');
    expect(normalizeSlashes('\t/path/to/file\n')).toBe('path/to/file');
  });

  it('removes leading slashes', () => {
    expect(normalizeSlashes('/path/to/file')).toBe('path/to/file');
    expect(normalizeSlashes('///path/to/file')).toBe('path/to/file');
  });

  it('removes trailing slashes', () => {
    expect(normalizeSlashes('path/to/file/')).toBe('path/to/file');
    expect(normalizeSlashes('path/to/file///')).toBe('path/to/file');
  });

  it('removes both leading and trailing slashes', () => {
    expect(normalizeSlashes('/path/to/file/')).toBe('path/to/file');
    expect(normalizeSlashes('///path/to/file///')).toBe('path/to/file');
  });

  it('replaces multiple consecutive slashes with single slash', () => {
    expect(normalizeSlashes('path//to///file')).toBe('path/to/file');
    expect(normalizeSlashes('path////to//file')).toBe('path/to/file');
  });

  it('handles paths with only slashes', () => {
    expect(normalizeSlashes('/')).toBe('');
    expect(normalizeSlashes('///')).toBe('');
    expect(normalizeSlashes('  ///  ')).toBe('');
  });

  it('handles empty strings', () => {
    expect(normalizeSlashes('')).toBe('');
    expect(normalizeSlashes('   ')).toBe('');
  });

  it('handles single segment paths', () => {
    expect(normalizeSlashes('file')).toBe('file');
    expect(normalizeSlashes('/file')).toBe('file');
    expect(normalizeSlashes('file/')).toBe('file');
    expect(normalizeSlashes('/file/')).toBe('file');
  });

  it('handles complex paths with all normalization needs', () => {
    expect(normalizeSlashes('  //path//to///file//  ')).toBe('path/to/file');
    expect(normalizeSlashes('///root///sub///dir///')).toBe('root/sub/dir');
  });
});

describe('extractSiteNameFromWebUrl', () => {
  it('extracts site name from a regular site URL', () => {
    expect(extractSiteNameFromWebUrl('https://contoso.sharepoint.com/sites/WealthManagement')).toBe(
      'WealthManagement',
    );
  });

  it('extracts full path for a subsite URL', () => {
    expect(
      extractSiteNameFromWebUrl('https://contoso.sharepoint.com/sites/WealthManagement/WMSub1'),
    ).toBe('WealthManagement/WMSub1');
  });

  it('extracts full path for a deeply nested subsite URL', () => {
    expect(
      extractSiteNameFromWebUrl(
        'https://contoso.sharepoint.com/sites/WealthManagement/WMSub1/Nested',
      ),
    ).toBe('WealthManagement/WMSub1/Nested');
  });

  it('decodes URL-encoded segments', () => {
    expect(
      extractSiteNameFromWebUrl('https://contoso.sharepoint.com/sites/Wealth%20Management'),
    ).toBe('Wealth Management');
  });

  it('decodes URL-encoded subsite segments', () => {
    expect(
      extractSiteNameFromWebUrl('https://contoso.sharepoint.com/sites/My%20Site/Sub%20Site'),
    ).toBe('My Site/Sub Site');
  });

  it('throws when URL has no /sites/ prefix', () => {
    expect(() => extractSiteNameFromWebUrl('https://contoso.sharepoint.com/teams/Team')).toThrow();
  });
});

describe('encodeSiteNameForPath', () => {
  it('returns plain names unchanged', () => {
    expect(encodeSiteNameForPath('WealthManagement')).toBe('WealthManagement');
  });

  it('preserves slashes between segments', () => {
    expect(encodeSiteNameForPath('WealthManagement/WMSub1')).toBe('WealthManagement/WMSub1');
  });

  it('encodes spaces within segments', () => {
    expect(encodeSiteNameForPath('Wealth Management')).toBe('Wealth%20Management');
  });

  it('encodes spaces in each segment independently', () => {
    expect(encodeSiteNameForPath('Wealth Management/WM Sub')).toBe('Wealth%20Management/WM%20Sub');
  });

  it('encodes special characters within segments', () => {
    expect(encodeSiteNameForPath("lorand's files")).toBe("lorand's%20files");
  });
});

describe('isAncestorOfRootPath', () => {
  describe('when path is an ancestor', () => {
    it('returns true for direct parent', () => {
      expect(isAncestorOfRootPath('/Top', '/Top/Middle/IngestionRoot')).toBe(true);
      expect(isAncestorOfRootPath('/Top/Middle', '/Top/Middle/IngestionRoot')).toBe(true);
    });

    it('returns true for grandparent', () => {
      expect(isAncestorOfRootPath('/Top', '/Top/Middle/IngestionRoot/SubFolder')).toBe(true);
      expect(isAncestorOfRootPath('/Root', '/Root/Project/Team/Scope')).toBe(true);
    });

    it('returns true for deeper ancestors', () => {
      expect(isAncestorOfRootPath('/A', '/A/B/C/D/E')).toBe(true);
      expect(isAncestorOfRootPath('/A/B', '/A/B/C/D/E')).toBe(true);
      expect(isAncestorOfRootPath('/A/B/C', '/A/B/C/D/E')).toBe(true);
    });
  });

  describe('when path is not an ancestor', () => {
    it('returns false when path equals rootPath', () => {
      expect(isAncestorOfRootPath('/Top/Middle/IngestionRoot', '/Top/Middle/IngestionRoot')).toBe(
        false,
      );
      expect(isAncestorOfRootPath('/Root', '/Root')).toBe(false);
    });

    it('returns false when path is a child of rootPath', () => {
      expect(
        isAncestorOfRootPath('/Top/Middle/IngestionRoot/Folder', '/Top/Middle/IngestionRoot'),
      ).toBe(false);
      expect(
        isAncestorOfRootPath('/Top/Middle/IngestionRoot/Sub/Deep', '/Top/Middle/IngestionRoot'),
      ).toBe(false);
    });

    it('returns false when path is a sibling', () => {
      expect(isAncestorOfRootPath('/Top/Other', '/Top/Middle/IngestionRoot')).toBe(false);
      expect(isAncestorOfRootPath('/Different', '/Top/Middle/IngestionRoot')).toBe(false);
    });

    it('returns false when path shares prefix but is not ancestor', () => {
      expect(isAncestorOfRootPath('/Top/Middle/Other', '/Top/Middle/IngestionRoot')).toBe(false);
      expect(isAncestorOfRootPath('/Top/MiddleX', '/Top/Middle/IngestionRoot')).toBe(false);
    });

    it('returns false when path is longer but not a child', () => {
      expect(isAncestorOfRootPath('/Top/Middle/IngestionRootX', '/Top/Middle/IngestionRoot')).toBe(
        false,
      );
    });
  });

  describe('edge cases', () => {
    it('handles empty paths', () => {
      expect(isAncestorOfRootPath('', '/Root')).toBe(true);
      expect(isAncestorOfRootPath('/Root', '')).toBe(false);
    });

    it('handles root path', () => {
      // Root path '/' is an ancestor of any root path (except when root path itself is '/')
      expect(isAncestorOfRootPath('/', '/Root')).toBe(true);
      expect(isAncestorOfRootPath('/', '/Top/Middle/IngestionRoot')).toBe(true);
      expect(isAncestorOfRootPath('/', '/A/B/C')).toBe(true);
      expect(isAncestorOfRootPath('/', '/')).toBe(false);
    });

    it('handles single segment paths', () => {
      expect(isAncestorOfRootPath('/A', '/A/B')).toBe(true);
      expect(isAncestorOfRootPath('/A', '/A')).toBe(false);
      expect(isAncestorOfRootPath('/A/B', '/A')).toBe(false);
    });

    it('handles paths with same prefix but different structure', () => {
      expect(isAncestorOfRootPath('/Top/Middle', '/Top/MiddleX')).toBe(false);
      expect(isAncestorOfRootPath('/Top/MiddleX', '/Top/Middle')).toBe(false);
    });
  });
});
