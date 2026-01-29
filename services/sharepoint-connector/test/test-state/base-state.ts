import type { SimplePermission } from '../../src/microsoft-apis/graph/types/sharepoint.types';
import type { FileAccessKey } from '../../src/unique-api/unique-files/unique-files.types';
import type { UniqueMockSeedState } from '../test-utils/unique-stateful-mock';

export interface SharepointFileMock {
  id: string;
  name: string;
  mimeType: string;
  size: number;
  syncFlag: boolean;
}

export interface SharepointFolderMock {
  id: string;
  name: string;
}

export interface UniqueFileMock {
  id: string;
}

export interface UniqueScopeMock {
  id: string;
  name: string;
  externalId: string | null;
}

export interface HierarchicalSharepointFileNode {
  type: 'file';
  mock: SharepointFileMock;
  permissions?: SimplePermission[];
  unique?: UniqueFileMock;
}

export interface HierarchicalSharepointFolderNode {
  type: 'folder';
  mock: SharepointFolderMock;
  children: HierarchicalSharepointNode[];
}

export type HierarchicalSharepointNode =
  | HierarchicalSharepointFileNode
  | HierarchicalSharepointFolderNode;

export interface SharepointDriveLibraryState {
  type: 'drive';
  mock: {
    id: string;
    name: string;
  };
  content: HierarchicalSharepointNode[];
}

export type SharepointLibraryState = SharepointDriveLibraryState;

export interface SharepointState {
  site: {
    siteId: string;
    displayName: string;
  };
  libraries: SharepointLibraryState[];
}

export interface HierarchicalUniqueFileNode {
  type: 'file';
  mock: UniqueFileMock;
  sharepoint: { itemId: string; siteId: string };
  seed?: {
    title: string;
    mimeType: string;
    byteSize?: number | null;
    fileAccess?: FileAccessKey[];
  };
}

export interface HierarchicalUniqueScopeNode {
  type: 'scope';
  mock: UniqueScopeMock;
  children: HierarchicalUniqueNode[];
}

export type HierarchicalUniqueNode = HierarchicalUniqueScopeNode | HierarchicalUniqueFileNode;

export interface ScenarioState {
  sharepoint: SharepointState;
  unique: {
    tree: HierarchicalUniqueScopeNode;
    seed: UniqueMockSeedState;
  };
}

export const baseState: ScenarioState = {
  sharepoint: {
    site: {
      siteId: '11111111-1111-4111-8111-111111111111',
      displayName: 'Test Site',
    },
    libraries: [
      {
        type: 'drive',
        mock: {
          id: 'drive-1',
          name: 'Documents',
        },
        content: [
          {
            type: 'file',
            mock: {
              id: 'item-1',
              name: 'test.pdf',
              mimeType: 'application/pdf',
              size: 1234,
              syncFlag: true,
            },
            permissions: [
              {
                id: 'perm-1',
                grantedToV2: {
                  user: {
                    id: 'graph-user-1',
                    email: 'user@example.com',
                  },
                },
              },
            ],
            unique: { id: 'unique-content-1' },
          },
        ],
      },
    ],
  },
  unique: {
    seed: {
      users: [{ id: 'unique-user-1', email: 'user@example.com', active: true }],
      scopes: [{ id: 'scope_root_1', name: 'RootScope', parentId: null, externalId: null }],
    },
    tree: {
      type: 'scope',
      mock: {
        id: 'scope_root_1',
        name: 'RootScope',
        externalId: null,
      },
      children: [
        {
          type: 'file',
          mock: { id: 'unique-content-1' },
          sharepoint: {
            siteId: '11111111-1111-4111-8111-111111111111',
            itemId: 'item-1',
          },
          seed: {
            title: 'test.pdf',
            mimeType: 'application/pdf',
            byteSize: 1234,
          },
        },
      ],
    },
  },
};
