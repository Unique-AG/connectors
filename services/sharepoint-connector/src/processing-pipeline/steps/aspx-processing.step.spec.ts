import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ProcessingContext } from '../types/processing-context';
import { AspxProcessingStep } from './aspx-processing.step';

describe('AspxProcessingStep', () => {
  let step: AspxProcessingStep;

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
    },
    ...overrides,
  });

  it('passes through non-ASPX files unchanged', async () => {
    const context = createContext({ fileName: 'document.pdf' });
    const result = await step.execute(context);
    expect(result).toBe(context);
    expect(result.contentBuffer).toBeUndefined();
  });

  it('processes ASPX files with CanvasContent1', async () => {
    const context = createContext({
      metadata: {
        ...createContext().metadata,
        listItemFields: {
          Title: 'Test Page',
          CanvasContent1: '<p>Canvas content</p>',
          Author: { FirstName: 'John', LastName: 'Doe' },
        },
      },
    });

    const result = await step.execute(context);

    expect(result.metadata.mimeType).toBe('text/html');
    const html = result.contentBuffer?.toString();
    expect(html).toContain('<h2>Test Page</h2>');
    expect(html).toContain('<h4>John Doe</h4>');
    expect(html).toContain('<p>Canvas content</p>');
  });

  it('processes ASPX files with WikiField when CanvasContent1 is empty', async () => {
    const context = createContext({
      metadata: {
        ...createContext().metadata,
        listItemFields: {
          Title: 'Wiki Page',
          WikiField: '<p>Wiki content</p>',
          Author: { FirstName: 'Jane', LastName: 'Smith' },
        },
      },
    });

    const result = await step.execute(context);
    const html = result.contentBuffer?.toString();
    expect(html).toContain('<h2>Wiki Page</h2>');
    expect(html).toContain('<h4>Jane Smith</h4>');
    expect(html).toContain('<p>Wiki content</p>');
  });

  it('falls back to filename when Title is missing', async () => {
    const context = createContext({
      metadata: {
        ...createContext().metadata,
        listItemFields: {
          CanvasContent1: '<p>Content</p>',
        },
      },
    });

    const result = await step.execute(context);
    const html = result.contentBuffer?.toString();
    expect(html).toContain('<h2>test.aspx</h2>');
  });

  it('handles missing author information', async () => {
    const context = createContext({
      metadata: {
        ...createContext().metadata,
        listItemFields: {
          Title: 'No Author Page',
          CanvasContent1: '<p>Content</p>',
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
    const context = createContext({
      metadata: {
        ...createContext().metadata,
        listItemFields: {
          Title: 'Partial Author',
          CanvasContent1: '<p>Content</p>',
          Author: { FirstName: 'John' },
        },
      },
    });

    const result = await step.execute(context);
    const html = result.contentBuffer?.toString();
    expect(html).toContain('<h4>John</h4>');
  });

  it('converts relative links to absolute links', async () => {
    const context = createContext({
      metadata: {
        ...createContext().metadata,
        listItemFields: {
          Title: 'Link Test',
          CanvasContent1: '<a href="/sites/test/page.aspx">Link</a>',
        },
      },
    });

    const result = await step.execute(context);
    const html = result.contentBuffer?.toString();
    expect(html).toContain('href="https://contoso.sharepoint.com/sites/test/page.aspx"');
  });

  it('handles empty content', async () => {
    const context = createContext({
      metadata: {
        ...createContext().metadata,
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
    const context = createContext({
      fileName: 'Test.ASPX',
      metadata: {
        ...createContext().metadata,
        listItemFields: {
          Title: 'Case Test',
          CanvasContent1: '<p>Content</p>',
        },
      },
    });

    const result = await step.execute(context);
    expect(result.metadata.mimeType).toBe('text/html');
    const html = result.contentBuffer?.toString();
    expect(html).toContain('<h2>Case Test</h2>');
  });
});
