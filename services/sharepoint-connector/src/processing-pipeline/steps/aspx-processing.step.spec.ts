import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { MsGraphSitePage } from '../../msgraph/types/pipeline-item.interface';
import type { ProcessingContext } from '../types/processing-context';
import { AspxProcessingStep } from './aspx-processing.step';

describe('AspxProcessingStep', () => {
  let step: AspxProcessingStep;

  const mockSitePage: MsGraphSitePage = {
    itemType: 'sitePage',
    id: 'page-1',
    name: 'test.aspx',
    size: 512,
    webUrl: 'https://sharepoint.example.com/test.aspx',
    lastModifiedDateTime: '2024-01-01T00:00:00Z',
    siteId: 'site-1',
    siteWebUrl: 'https://sharepoint.example.com',
    driveId: 'sitepages-list',
    driveName: 'SitePages',
    folderPath: '/',
    listItem: {
      fields: {
        FileLeafRef: 'test.aspx',
        Title: 'Test Page',
      },
    },
  };

  beforeEach(async () => {
    const { unit } = await TestBed.solitary(AspxProcessingStep)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'sharepoint.baseUrl') {
            return 'https://contoso.sharepoint.com';
          }
          return undefined;
        }),
      }))
      .compile();
    step = unit;
  });

  const createContext = (overrides: Partial<ProcessingContext> = {}): ProcessingContext => ({
    correlationId: 'c1',
    fileId: 'f1',
    fileName: 'test.aspx',
    fileSize: 0,
    siteUrl: 'https://contoso.sharepoint.com/sites/test',
    libraryName: 'lib',
    startTime: new Date(),
    metadata: {
      siteId: 'site',
      driveId: 'drive',
      mimeType: 'text/html',
      isFolder: false,
      listItemFields: {},
      driveName: 'Documents',
      folderPath: '/test',
      lastModifiedDateTime: '2024-01-01T00:00:00Z',
      sourceItem: mockSitePage,
    },
    ...overrides,
  });

  it('passes through non-ASPX files unchanged', async () => {
    const context = createContext({
      fileName: 'document.pdf',
      contentBuffer: Buffer.from('pdf content')
    });
    const result = await step.execute(context);
    expect(result).toBe(context);
    expect(result.contentBuffer?.toString()).toBe('pdf content');
  });

  it('processes ASPX files with CanvasContent1', async () => {
    mockGraphApiService.getSitePageContent = vi.fn().mockResolvedValue({
      canvasContent: '<p>Canvas content</p>',
      wikiField: undefined,
    });

    const context = createContext({
      metadata: {
        ...createContext().metadata,
        sourceItem: mockSitePage,
        listItemFields: {
          Title: 'Test Page',
          Author: 'John Doe',
        },
      },
    });

    const result = await step.execute(context);

    expect(mockGraphApiService.getSitePageContent).toHaveBeenCalledWith('site', 'drive', 'f1');
    expect(result.metadata.mimeType).toBe('text/html');
    const html = result.contentBuffer?.toString();
    expect(html).toContain('<h2>Test Page</h2>');
    expect(html).toContain('<h4>John Doe</h4>');
    expect(html).toContain('<p>Canvas content</p>');
  });

  it('processes ASPX files with WikiField when CanvasContent1 is empty', async () => {
    mockGraphApiService.getSitePageContent = vi.fn().mockResolvedValue({
      canvasContent: undefined,
      wikiField: '<p>Wiki content</p>',
    });

    const context = createContext({
      metadata: {
        ...createContext().metadata,
        sourceItem: mockSitePage,
        listItemFields: {
          Title: 'Wiki Page',
          Author: 'Jane Smith',
        },
      },
    });

    const result = await step.execute(context);
    expect(mockGraphApiService.getSitePageContent).toHaveBeenCalledWith('site', 'drive', 'f1');
    const html = result.contentBuffer?.toString();
    expect(html).toContain('<h2>Wiki Page</h2>');
    expect(html).toContain('<h4>Jane Smith</h4>');
    expect(html).toContain('<p>Wiki content</p>');
  });

  it('falls back to filename when Title is missing', async () => {
    mockGraphApiService.getSitePageContent = vi.fn().mockResolvedValue({
      canvasContent: '<p>Content</p>',
      wikiField: undefined,
    });

    const context = createContext({
      metadata: {
        ...createContext().metadata,
        sourceItem: mockSitePage,
        listItemFields: {},
      },
    });

    const result = await step.execute(context);
    const html = result.contentBuffer?.toString();
    expect(html).toContain('<h2>test.aspx</h2>');
  });

  it('handles missing author information', async () => {
    mockGraphApiService.getSitePageContent = vi.fn().mockResolvedValue({
      canvasContent: '<p>Content</p>',
      wikiField: undefined,
    });

    const context = createContext({
      metadata: {
        ...createContext().metadata,
        sourceItem: mockSitePage,
        listItemFields: {
          Title: 'No Author Page',
        },
      },
    });

    const result = await step.execute(context);
    const html = result.contentBuffer?.toString();
    expect(html).toContain('<h2>No Author Page</h2>');
    expect(html).not.toContain('<h4>');
    expect(html).toContain('<p>Content</p>');
  });

  it('handles partial author information', async () => {
    mockGraphApiService.getSitePageContent = vi.fn().mockResolvedValue({
      canvasContent: '<p>Content</p>',
      wikiField: undefined,
    });

    const context = createContext({
      metadata: {
        ...createContext().metadata,
        sourceItem: mockSitePage,
        listItemFields: {
          Title: 'Partial Author',
          Author: 'John',
        },
      },
    });

    const result = await step.execute(context);
    const html = result.contentBuffer?.toString();
    expect(html).toContain('<h4>John</h4>');
  });

  it('converts relative links to absolute links', async () => {
    mockGraphApiService.getSitePageContent = vi.fn().mockResolvedValue({
      canvasContent: '<a href="/sites/test/page.aspx">Link</a>',
      wikiField: undefined,
    });

    const context = createContext({
      metadata: {
        ...createContext().metadata,
        sourceItem: mockSitePage,
        listItemFields: {
          Title: 'Link Test',
        },
      },
    });

    const result = await step.execute(context);
    const html = result.contentBuffer?.toString();
    expect(html).toContain('href="https://contoso.sharepoint.com/sites/test/page.aspx"');
  });

  it('handles empty content', async () => {
    mockGraphApiService.getSitePageContent = vi.fn().mockResolvedValue({
      canvasContent: undefined,
      wikiField: undefined,
    });

    const context = createContext({
      metadata: {
        ...createContext().metadata,
        sourceItem: mockSitePage,
        listItemFields: {
          Title: 'Empty Page',
        },
      },
    });

    const result = await step.execute(context);
    const html = result.contentBuffer?.toString();
    expect(html).toContain('<h2>Empty Page</h2>');
    expect(html).toContain('<div>');
    expect(html).toContain('</div>');
  });

  it('handles case insensitive ASPX detection', async () => {
    mockGraphApiService.getSitePageContent = vi.fn().mockResolvedValue({
      canvasContent: '<p>Content</p>',
      wikiField: undefined,
    });

    const context = createContext({
      fileName: 'Test.ASPX',
      metadata: {
        ...createContext().metadata,
        sourceItem: mockSitePage,
        listItemFields: {
          Title: 'Case Test',
        },
      },
    });

    const result = await step.execute(context);
    expect(result.metadata.mimeType).toBe('text/html');
    const html = result.contentBuffer?.toString();
    expect(html).toContain('<h2>Case Test</h2>');
  });
});
