import type { RequestDocument, Variables } from 'graphql-request';
import { vi } from 'vitest';

export class MockUniqueGraphqlClient {
  // Mutable responses per operation (can be customized per test)
  public responses: Record<string, unknown> = {
    User: {
      me: {
        user: {
          id: 'unique-user-1',
        },
      },
    },
    PaginatedScope: {
      paginatedScope: {
        totalCount: 1,
        nodes: [
          {
            id: 'scope_root_1',
            name: 'RootScope',
            parentId: null,
            externalId: null,
          },
        ],
      },
    },
    CreateScopeAccesses: {
      createScopeAccesses: true,
    },
    UpdateScope: {
      updateScope: {
        id: 'scope_root_1',
        name: 'RootScope',
        externalId: 'spc:site:11111111-1111-4111-8111-111111111111',
      },
    },
    ListUsers: {
      listUsers: {
        totalCount: 1,
        nodes: [
          {
            id: 'unique-user-2',
            active: true,
            email: 'user@example.com',
          },
        ],
      },
    },
    ListGroups: {
      listGroups: [],
    },
    CreateGroup: {
      createGroup: {
        id: 'unique-group-1',
        name: 'Group A',
        externalId: 'SPC-test',
      },
    },
    UpdateGroup: {
      updateGroup: {
        id: 'unique-group-1',
        name: 'Group A',
        externalId: 'SPC-test',
      },
    },
    AddGroupMembers: {
      addGroupMembers: [
        {
          entityId: 'unique-user-2',
          groupId: 'unique-group-1',
        },
      ],
    },
    RemoveGroupMember: {
      removeGroupMember: true,
    },
    DeleteGroup: {
      deleteGroup: {
        id: 'unique-group-1',
      },
    },
    ContentUpsert: {
      contentUpsert: {
        id: 'unique-content-1',
        key: '11111111-1111-4111-8111-111111111111/item-1',
        title: 'test.pdf',
        byteSize: 1234,
        mimeType: 'application/pdf',
        ownerType: 'Scope',
        ownerId: 'scope_root_1',
        writeUrl: 'https://upload.test.example.com/upload?key=test-key',
        readUrl: 'https://read.test.example.com/file/test-key',
        createdAt: '2025-01-01T00:00:00Z',
        internallyStoredAt: null,
        source: {
          kind: 'MICROSOFT_365_SHAREPOINT',
          name: 'Sharepoint',
        },
      },
    },
    PaginatedContent: {
      paginatedContent: {
        nodes: [
          {
            id: 'unique-content-1',
            fileAccess: ['u:unique-user-1R', 'u:unique-user-1W', 'u:unique-user-1M'],
            key: '11111111-1111-4111-8111-111111111111/item-1',
            ownerType: 'Scope',
            ownerId: 'scope_root_1',
          },
        ],
        totalCount: 1,
      },
    },
    CreateFileAccessesForContents: {
      createFileAccessesForContents: true,
    },
    RemoveFileAccessesForContents: {
      removeFileAccessesForContents: true,
    },
    DeleteScopeAccesses: {
      deleteScopeAccesses: true,
    },
  };

  public request = vi
    .fn()
    .mockImplementation(
      async <T, V extends Variables = Variables>(
        document: RequestDocument,
        _variables?: V,
      ): Promise<T> => {
        const operationName = this.extractOperationName(document);
        return (this.responses[operationName] as T) || ({} as T);
      },
    );

  private extractOperationName(document: RequestDocument): string {
    const docString = typeof document === 'string' ? document : document.toString();
    const match = docString.match(/(?:mutation|query)\s+(\w+)/);
    return match?.[1] || 'Unknown';
  }
}
