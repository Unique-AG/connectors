import { describe, expect, it } from 'vitest';
import { buildSharepointFileKey, buildSharepointPartialKey } from './sharepoint-key.util';

describe('buildSharepointFileKey', () => {
  it('should build scope-based key when scopeId is provided', () => {
    const result = buildSharepointFileKey({
      scopeId: 'scope123',
      siteId: 'site456',
      driveName: 'Documents',
      folderPath: '/folder/subfolder',
      fileId: 'file789',
      fileName: 'document.docx',
    });

    expect(result).toBe('sharepoint_scope_scope123_file789');
  });

  it('should build path-based key when scopeId is null', () => {
    const result = buildSharepointFileKey({
      scopeId: null,
      siteId: 'site456',
      driveName: 'Documents',
      folderPath: '/folder/subfolder',
      fileId: 'file789',
      fileName: 'document.docx',
    });

    expect(result).toBe('site456/Documents/folder/subfolder/document.docx');
  });

  it('should build path-based key when scopeId is undefined', () => {
    const result = buildSharepointFileKey({
      siteId: 'site456',
      driveName: 'Documents',
      folderPath: '/folder/subfolder',
      fileId: 'file789',
      fileName: 'document.docx',
    });

    expect(result).toBe('site456/Documents/folder/subfolder/document.docx');
  });

  it('should handle empty folderPath', () => {
    const result = buildSharepointFileKey({
      siteId: 'site456',
      driveName: 'Documents',
      folderPath: '',
      fileId: 'file789',
      fileName: 'document.docx',
    });

    expect(result).toBe('site456/Documents/document.docx');
  });

  it('should handle root folderPath', () => {
    const result = buildSharepointFileKey({
      siteId: 'site456',
      driveName: 'Documents',
      folderPath: '/',
      fileId: 'file789',
      fileName: 'document.docx',
    });

    expect(result).toBe('site456/Documents/document.docx');
  });

  it('should trim slashes from inputs', () => {
    const result = buildSharepointFileKey({
      siteId: '/site456/',
      driveName: '/Documents/',
      folderPath: '/folder/subfolder/',
      fileId: 'file789',
      fileName: 'document.docx',
    });

    expect(result).toBe('site456/Documents/folder/subfolder/document.docx');
  });

  it('should handle extra spaces in inputs', () => {
    const result = buildSharepointFileKey({
      siteId: '  site456  ',
      driveName: '  Documents  ',
      folderPath: '  /folder/subfolder  ',
      fileId: 'file789',
      fileName: '  document.docx  ',
    });

    expect(result).toBe('site456/Documents/folder/subfolder/document.docx');
  });

  it('should filter out empty segments', () => {
    const result = buildSharepointFileKey({
      siteId: '',
      driveName: 'Documents',
      folderPath: '',
      fileId: 'file789',
      fileName: 'document.docx',
    });

    expect(result).toBe('Documents/document.docx');
  });
});

describe('buildSharepointPartialKey', () => {
  it('should build scope-based partial key when scopeId is provided', () => {
    const result = buildSharepointPartialKey({
      scopeId: 'scope123',
      siteId: 'site456',
    });

    expect(result).toBe('sharepoint_scope_scope123_');
  });

  it('should build path-based partial key when scopeId is null', () => {
    const result = buildSharepointPartialKey({
      scopeId: null,
      siteId: 'site456',
    });

    expect(result).toBe('site456');
  });

  it('should build path-based partial key when scopeId is undefined', () => {
    const result = buildSharepointPartialKey({
      siteId: 'site456',
    });

    expect(result).toBe('site456');
  });

  it('should trim slashes from siteId', () => {
    const result = buildSharepointPartialKey({
      siteId: '/site456/',
    });

    expect(result).toBe('site456');
  });
});
