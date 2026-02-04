import type { Drive } from '@microsoft/microsoft-graph-types';
import type {
  DriveItem,
  SimplePermission,
} from '../../src/microsoft-apis/graph/types/sharepoint.types';
import type { FileAccessKey } from '../../src/unique-api/unique-files/unique-files.types';
import type { UniqueStatefulMock } from '../test-utils/unique-stateful-mock';
import type {
  HierarchicalSharepointFolderNode,
  HierarchicalSharepointNode,
  HierarchicalUniqueNode,
  HierarchicalUniqueScopeNode,
  ScenarioState,
  SharepointDriveLibraryState,
  SharepointState,
} from './base-state';

export function applyScenarioState(params: {
  graphClient: {
    drives: Drive[];
    driveItems: DriveItem[];
    permissions: Record<string, SimplePermission[]>;
  };
  uniqueMock: UniqueStatefulMock;
  state: ScenarioState;
}): void {
  applySharepointState(params.graphClient, params.state.sharepoint);
  params.uniqueMock.reset();
  params.uniqueMock.seed(params.state.unique.seed);
  applyUniqueState(params.uniqueMock, params.state.unique.tree);
}

export function applySharepointState(
  graphClient: {
    drives: Drive[];
    driveItems: DriveItem[];
    permissions: Record<string, SimplePermission[]>;
  },
  sharepoint: SharepointState,
): void {
  const driveLibraries = sharepoint.libraries.filter(
    (l): l is SharepointDriveLibraryState => l.type === 'drive',
  );

  if (driveLibraries.length === 0) {
    throw new Error('Scenario has no drive library');
  }

  const driveTemplate = graphClient.drives[0];
  const itemTemplate = graphClient.driveItems[0];
  if (!driveTemplate || !itemTemplate) {
    throw new Error('MockGraphClient missing default templates (drive or driveItem)');
  }

  // Drives
  graphClient.drives = driveLibraries.map((lib) => ({
    ...driveTemplate,
    id: lib.mock.id,
    name: lib.mock.name,
  }));

  // Drive items
  const flattened: DriveItem[] = [];
  const permissions: Record<string, SimplePermission[]> = {};

  for (const lib of driveLibraries) {
    for (const node of lib.content) {
      flattenSharepointNode({
        node,
        sharepointSiteId: sharepoint.site.siteId,
        driveId: lib.mock.id,
        driveName: lib.mock.name,
        itemTemplate,
        outItems: flattened,
        outPermissions: permissions,
      });
    }
  }

  graphClient.driveItems = flattened;
  graphClient.permissions = permissions;
}

function flattenSharepointNode(input: {
  node: HierarchicalSharepointNode;
  sharepointSiteId: string;
  driveId: string;
  driveName: string;
  itemTemplate: DriveItem;
  outItems: DriveItem[];
  outPermissions: Record<string, SimplePermission[]>;
}): void {
  if (input.node.type === 'file') {
    const item = structuredClone(input.itemTemplate);

    item.id = input.node.mock.id;
    item.name = input.node.mock.name;
    item.size = input.node.mock.size;
    item.parentReference.driveId = input.driveId;
    item.parentReference.name = input.driveName;
    item.parentReference.siteId = input.sharepointSiteId;

    if (item.file) {
      item.file.mimeType = input.node.mock.mimeType;
    }

    if (item.listItem?.fields) {
      item.listItem.fields.SyncFlag = input.node.mock.syncFlag;
      item.listItem.fields.FileLeafRef = input.node.mock.name;
      item.listItem.fields.ItemChildCount = '0';
      item.listItem.fields.FolderChildCount = '0';
    }

    input.outItems.push(item);

    if (input.node.permissions) {
      input.outPermissions[item.id] = input.node.permissions;
    }

    return;
  }

  // folder
  const folderNode: HierarchicalSharepointFolderNode = input.node;
  const folderItem = structuredClone(input.itemTemplate);
  folderItem.id = folderNode.mock.id;
  folderItem.name = folderNode.mock.name;
  folderItem.size = 0;
  folderItem.parentReference.driveId = input.driveId;
  folderItem.parentReference.name = input.driveName;
  folderItem.parentReference.siteId = input.sharepointSiteId;

  folderItem.folder = { childCount: folderNode.children.length };
  delete folderItem.file;

  if (folderItem.listItem?.fields) {
    folderItem.listItem.fields.SyncFlag = true;
    folderItem.listItem.fields.FileLeafRef = folderItem.name;
    folderItem.listItem.fields.ItemChildCount = '0';
    folderItem.listItem.fields.FolderChildCount = String(folderNode.children.length);
  }

  input.outItems.push(folderItem);

  for (const child of folderNode.children) {
    flattenSharepointNode({ ...input, node: child });
  }
}

export function applyUniqueState(
  uniqueMock: UniqueStatefulMock,
  tree: HierarchicalUniqueScopeNode,
): void {
  // We intentionally do NOT call uniqueMock.reset/seed here; caller controls reset/seed ordering.
  // This function flattens explicit tree into seed data and merges into the current store via seed().
  const scopes: Array<{
    id: string;
    name: string;
    parentId: string | null;
    externalId: string | null;
  }> = [];

  const contents: Array<{
    id?: string;
    key: string;
    title: string;
    mimeType: string;
    ownerId: string;
    byteSize?: number | null;
    fileAccess?: FileAccessKey[];
  }> = [];

  flattenUniqueNode({
    node: tree,
    parentScopeId: null,
    outScopes: scopes,
    outContents: contents,
  });

  uniqueMock.seed({
    scopes,
    contents: contents.map((c) => ({
      id: c.id,
      key: c.key,
      title: c.title,
      mimeType: c.mimeType,
      ownerId: c.ownerId,
      byteSize: c.byteSize,
      fileAccess: c.fileAccess,
    })),
  });
}

function flattenUniqueNode(input: {
  node: HierarchicalUniqueNode;
  parentScopeId: string | null;
  outScopes: Array<{
    id: string;
    name: string;
    parentId: string | null;
    externalId: string | null;
  }>;
  outContents: Array<{
    id?: string;
    key: string;
    title: string;
    mimeType: string;
    ownerId: string;
    byteSize?: number | null;
    fileAccess?: FileAccessKey[];
  }>;
}): void {
  if (input.node.type === 'scope') {
    input.outScopes.push({
      id: input.node.mock.id,
      name: input.node.mock.name,
      parentId: input.parentScopeId,
      externalId: input.node.mock.externalId,
    });

    for (const child of input.node.children) {
      flattenUniqueNode({
        node: child,
        parentScopeId: input.node.mock.id,
        outScopes: input.outScopes,
        outContents: input.outContents,
      });
    }
    return;
  }

  const ownerId = input.parentScopeId ?? 'scope_root_1';
  const key = `${input.node.sharepoint.siteId}/${input.node.sharepoint.itemId}`;

  input.outContents.push({
    id: input.node.mock.id,
    key,
    title: input.node.seed?.title ?? 'file',
    mimeType: input.node.seed?.mimeType ?? 'application/octet-stream',
    ownerId,
    byteSize: input.node.seed?.byteSize,
    fileAccess: input.node.seed?.fileAccess,
  });
}
