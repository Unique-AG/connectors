import { beforeEach, describe, expect, it, vi } from 'vitest';
import { OneNoteGraphService } from './onenote-graph.service';

describe('OneNoteGraphService', () => {
  let service: OneNoteGraphService;

  const createMockClient = (responseValue: unknown, extraProps: Record<string, unknown> = {}) => ({
    api: vi.fn().mockReturnValue({
      select: vi.fn().mockReturnThis(),
      expand: vi.fn().mockReturnThis(),
      filter: vi.fn().mockReturnThis(),
      orderby: vi.fn().mockReturnThis(),
      top: vi.fn().mockReturnThis(),
      header: vi.fn().mockReturnThis(),
      get: vi.fn().mockResolvedValue({ value: responseValue, ...extraProps }),
      post: vi.fn().mockResolvedValue(responseValue),
      patch: vi.fn().mockResolvedValue(undefined),
      getStream: vi.fn(),
    }),
  });

  beforeEach(() => {
    vi.clearAllMocks();
    service = new OneNoteGraphService();
  });

  describe('listNotebooks', () => {
    it('returns parsed notebooks', async () => {
      const mockNotebooks = [
        {
          id: 'nb-1',
          displayName: 'My Notebook',
          createdDateTime: '2024-01-01T00:00:00Z',
          lastModifiedDateTime: '2024-06-01T00:00:00Z',
          isShared: true,
          userRole: 'Owner',
          links: {
            oneNoteWebUrl: { href: 'https://onenote.com/nb-1' },
          },
        },
      ];

      const client = createMockClient(mockNotebooks);
      // biome-ignore lint/suspicious/noExplicitAny: Test mock
      const result = await service.listNotebooks(client as any);

      expect(result).toHaveLength(1);
      expect(result[0]?.displayName).toBe('My Notebook');
      expect(result[0]?.links?.oneNoteWebUrl?.href).toBe('https://onenote.com/nb-1');
    });
  });

  describe('listSections', () => {
    it('returns parsed sections for a notebook', async () => {
      const mockSections = [
        {
          id: 'sec-1',
          displayName: 'Section A',
          createdDateTime: '2024-01-01T00:00:00Z',
          lastModifiedDateTime: '2024-06-01T00:00:00Z',
          isDefault: true,
        },
      ];

      const client = createMockClient(mockSections);
      // biome-ignore lint/suspicious/noExplicitAny: Test mock
      const result = await service.listSections(client as any, 'nb-1');

      expect(result).toHaveLength(1);
      expect(result[0]?.displayName).toBe('Section A');
    });
  });

  describe('listPages', () => {
    it('handles pagination with @odata.nextLink', async () => {
      const page1 = [
        {
          id: 'page-1',
          title: 'Page 1',
          createdDateTime: '2024-01-01T00:00:00Z',
          lastModifiedDateTime: '2024-06-01T00:00:00Z',
        },
      ];
      const page2 = [
        {
          id: 'page-2',
          title: 'Page 2',
          createdDateTime: '2024-02-01T00:00:00Z',
          lastModifiedDateTime: '2024-07-01T00:00:00Z',
        },
      ];

      const mockApi = vi.fn();
      const client = { api: mockApi };

      const chainMethods = {
        select: vi.fn().mockReturnThis(),
        orderby: vi.fn().mockReturnThis(),
        top: vi.fn().mockReturnThis(),
        get: vi.fn(),
      };

      mockApi.mockReturnValue(chainMethods);

      chainMethods.get
        .mockResolvedValueOnce({
          value: page1,
          '@odata.nextLink': 'https://graph.microsoft.com/next-page',
        })
        .mockResolvedValueOnce({
          value: page2,
        });

      // biome-ignore lint/suspicious/noExplicitAny: Test mock
      const result = await service.listPages(client as any, 'sec-1');

      expect(result).toHaveLength(2);
      expect(result[0]?.title).toBe('Page 1');
      expect(result[1]?.title).toBe('Page 2');
    });
  });

  describe('createNotebook', () => {
    it('creates a notebook via POST', async () => {
      const mockResponse = {
        id: 'new-nb',
        displayName: 'New Notebook',
        createdDateTime: '2024-06-01T00:00:00Z',
        lastModifiedDateTime: '2024-06-01T00:00:00Z',
      };

      const client = createMockClient(mockResponse);
      // biome-ignore lint/suspicious/noExplicitAny: Test mock
      const result = await service.createNotebook(client as any, 'New Notebook');

      expect(result.id).toBe('new-nb');
      expect(result.displayName).toBe('New Notebook');
    });
  });

  describe('createPage', () => {
    it('creates a page with XHTML content', async () => {
      const mockResponse = {
        id: 'new-page',
        title: 'Test Page',
        createdDateTime: '2024-06-01T00:00:00Z',
        lastModifiedDateTime: '2024-06-01T00:00:00Z',
      };

      const client = createMockClient(mockResponse);
      // biome-ignore lint/suspicious/noExplicitAny: Test mock
      const result = await service.createPage(client as any, 'sec-1', 'Test Page', '<p>Hello</p>');

      expect(result.id).toBe('new-page');
      expect(result.title).toBe('Test Page');
      expect(client.api).toHaveBeenCalledWith('/me/onenote/sections/sec-1/pages');
    });
  });

  describe('getDelta', () => {
    it('returns items and delta link on initial call', async () => {
      const mockItems = [
        { id: 'item-1', name: 'file.one' },
        { id: 'item-2', name: 'file.docx' },
      ];

      const mockApi = vi.fn();
      const client = { api: mockApi };

      mockApi.mockReturnValue({
        get: vi.fn().mockResolvedValue({
          value: mockItems,
          '@odata.deltaLink': 'https://graph.microsoft.com/delta?token=abc',
        }),
      });

      // biome-ignore lint/suspicious/noExplicitAny: Test mock
      const result = await service.getDelta(client as any);

      expect(result.items).toHaveLength(2);
      expect(result.nextDeltaLink).toBe('https://graph.microsoft.com/delta?token=abc');
      expect(mockApi).toHaveBeenCalledWith('/me/drive/root/delta');
    });

    it('uses provided delta link for incremental queries', async () => {
      const mockApi = vi.fn();
      const client = { api: mockApi };

      mockApi.mockReturnValue({
        get: vi.fn().mockResolvedValue({
          value: [],
          '@odata.deltaLink': 'https://graph.microsoft.com/delta?token=new',
        }),
      });

      const existingLink = 'https://graph.microsoft.com/delta?token=old';
      // biome-ignore lint/suspicious/noExplicitAny: Test mock
      const result = await service.getDelta(client as any, existingLink);

      expect(mockApi).toHaveBeenCalledWith(existingLink);
      expect(result.nextDeltaLink).toBe('https://graph.microsoft.com/delta?token=new');
    });
  });

  describe('getNotebookDriveItem', () => {
    it('percent-encodes special characters in notebook name for OData search', async () => {
      const notebookName = "Project (2024) $budget's";
      const mockApi = vi.fn();
      const client = { api: mockApi };

      const chainMethods = {
        select: vi.fn().mockReturnThis(),
        get: vi.fn(),
      };
      mockApi.mockReturnValue(chainMethods);

      chainMethods.get
        .mockResolvedValueOnce({ displayName: notebookName })
        .mockResolvedValueOnce({
          value: [
            {
              id: 'item-1',
              name: notebookName,
              parentReference: { driveId: 'drive-1', id: 'parent-1' },
              package: { type: 'oneNote' },
            },
          ],
        });

      // biome-ignore lint/suspicious/noExplicitAny: Test mock
      const result = await service.getNotebookDriveItem(client as any, 'nb-1');

      const searchCallPath = mockApi.mock.calls[1]?.[0] as string;
      expect(searchCallPath).not.toContain("'s");
      expect(searchCallPath).not.toContain('(2024)');
      expect(searchCallPath).not.toContain('$budget');
      expect(searchCallPath).toBe(
        `/me/drive/root/search(q='Project%20%282024%29%20%24budget%27s')`,
      );
      expect(result).toEqual({ driveId: 'drive-1', itemId: 'item-1' });
    });

    it('returns null when no drive items match', async () => {
      const mockApi = vi.fn();
      const client = { api: mockApi };

      const chainMethods = {
        select: vi.fn().mockReturnThis(),
        get: vi.fn(),
      };
      mockApi.mockReturnValue(chainMethods);

      chainMethods.get
        .mockResolvedValueOnce({ displayName: 'Notebook' })
        .mockResolvedValueOnce({ value: [] });

      // biome-ignore lint/suspicious/noExplicitAny: Test mock
      const result = await service.getNotebookDriveItem(client as any, 'nb-1');
      expect(result).toBeNull();
    });

    it('falls back to .onetoc2 file when no oneNote package found', async () => {
      const mockApi = vi.fn();
      const client = { api: mockApi };

      const chainMethods = {
        select: vi.fn().mockReturnThis(),
        get: vi.fn(),
      };
      mockApi.mockReturnValue(chainMethods);

      chainMethods.get
        .mockResolvedValueOnce({ displayName: 'My Notes' })
        .mockResolvedValueOnce({
          value: [
            {
              id: 'toc-1',
              name: 'My Notes.onetoc2',
              parentReference: { driveId: 'drive-1', id: 'parent-1' },
            },
          ],
        });

      // biome-ignore lint/suspicious/noExplicitAny: Test mock
      const result = await service.getNotebookDriveItem(client as any, 'nb-1');
      expect(result).toEqual({ driveId: 'drive-1', itemId: 'parent-1' });
    });
  });

  describe('getNotebookPermissions', () => {
    it('returns parsed permissions', async () => {
      const mockPermissions = [
        {
          id: 'perm-1',
          roles: ['read'],
          grantedToV2: { user: { email: 'user@example.com' } },
        },
      ];

      const client = createMockClient(mockPermissions);
      // biome-ignore lint/suspicious/noExplicitAny: Test mock
      const result = await service.getNotebookPermissions(client as any, 'drive-1', 'item-1');

      expect(result).toHaveLength(1);
      expect(result[0]?.grantedToV2?.user?.email).toBe('user@example.com');
    });

    it('returns empty array on error', async () => {
      const client = {
        api: vi.fn().mockReturnValue({
          get: vi.fn().mockRejectedValue(new Error('Forbidden')),
        }),
      };

      // biome-ignore lint/suspicious/noExplicitAny: Test mock
      const result = await service.getNotebookPermissions(client as any, 'drive-1', 'item-1');

      expect(result).toEqual([]);
    });
  });
});
