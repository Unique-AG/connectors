import { MockAgent, setGlobalDispatcher } from 'undici';
import { FakeUniqueRegistry } from './fake-unique-registry';
import { EXTERNAL_ID_PREFIX } from '../../src/utils/logging.util';

export const setupMockAgent = () => {
  const agent = new MockAgent();
  agent.disableNetConnect();
  setGlobalDispatcher(agent);
  return agent;
};

export const mockGraphAuth = (agent: MockAgent) => {
  const client = agent.get('https://login.microsoftonline.com');
  client
    .intercept({
      path: (p) => p.includes('/oauth2/v2.0/token'),
      method: 'POST',
    })
    .reply(200, (opts) => {
      return JSON.stringify({
        token_type: 'Bearer',
        expires_in: 3600,
        access_token: 'fake-graph-token',
      });
    }, { headers: { 'content-type': 'application/json' } })
    .persist();
};

export const mockUniqueAuth = (agent: MockAgent, oauthUrl: string) => {
  const url = new URL(oauthUrl);
  const client = agent.get(url.origin);
  client
    .intercept({
      path: url.pathname,
      method: 'POST',
    })
    .reply(200, (opts) => {
      return JSON.stringify({
        access_token: 'fake-unique-token',
        expires_in: 3600,
        token_type: 'Bearer',
        id_token: 'fake-id-token',
      });
    }, { headers: { 'content-type': 'application/json' } })
    .persist();
};

export const mockUniqueIngestion = (
  agent: MockAgent,
  baseUrl: string,
  registry: FakeUniqueRegistry,
) => {
  const url = new URL(baseUrl);
  const client = agent.get(url.origin);

  // File Diff REST API
  client
    .intercept({
      path: (p) => p.includes('/file-diff'),
      method: 'POST',
    })
    .reply(
      200,
      (opts) => {
        const body = typeof opts.body === 'string' ? JSON.parse(opts.body) : JSON.parse(opts.body.toString());
        return JSON.stringify(registry.handleFileDiff(body));
      },
      { headers: { 'content-type': 'application/json' } },
    )
    .persist();

  // GraphQL API
  client
    .intercept({
      path: (p) => p.includes('/graphql'),
      method: 'POST',
    })
    .reply(
      200,
      (opts) => {
        const body = typeof opts.body === 'string' ? JSON.parse(opts.body) : JSON.parse(opts.body.toString());
        const opName = body.query.match(/(?:query|mutation)\s+(\w+)/)?.[1] || body.operationName;
        
        if (opName === 'ContentUpsert' || body.query.includes('mutation ContentUpsert')) {
          return JSON.stringify({
            data: {
              contentUpsert: registry.handleContentUpsert(body.variables),
            },
          });
        }
        if (opName === 'PaginatedContentCount' || body.query.includes('query PaginatedContentCount')) {
          return JSON.stringify({
            data: {
              paginatedContent: {
                totalCount: registry.getFiles().length,
              },
            },
          });
        }
        if (opName === 'PaginatedContent' || body.query.includes('query PaginatedContent')) {
          const keys = body.variables.where?.key?.in;
          let nodes = registry.getFiles().map(f => ({
            id: f.id,
            key: f.key,
            fileAccess: Array.from(f.access),
            ownerType: f.ownerType,
            ownerId: f.ownerId
          }));
          
          if (keys) {
            nodes = nodes.filter(n => keys.includes(n.key));
          }

          return JSON.stringify({
            data: {
              paginatedContent: {
                totalCount: nodes.length,
                nodes,
              },
            },
          });
        }
        if (opName === 'ContentDelete' || body.query.includes('mutation ContentDelete')) {
          const id = body.variables.contentDeleteId;
          const file = registry.getFiles().find((f) => f.id === id);
          if (file) {
            registry.deleteFile(file.key);
          }
          return JSON.stringify({
            data: {
              contentDelete: true,
            },
          });
        }
        if (opName === 'ContentDeleteByContentIds' || body.query.includes('mutation ContentDeleteByContentIds')) {
          const ids = body.variables.contentIds;
          for (const id of ids) {
            const file = registry.getFiles().find((f) => f.id === id);
            if (file) {
              registry.deleteFile(file.key);
            }
          }
          return JSON.stringify({
            data: {
              contentDeleteByContentIds: ids.map((id: string) => ({ id })),
            },
          });
        }
        if (opName === 'CreateFileAccessesForContents' || body.query.includes('mutation CreateFileAccessesForContents')) {
          return JSON.stringify({
            data: {
              createFileAccessesForContents: registry.handleCreateFileAccesses(
                body.variables.fileAccesses,
              ),
            },
          });
        }
        if (opName === 'RemoveFileAccessesForContents' || body.query.includes('mutation RemoveFileAccessesForContents')) {
          return JSON.stringify({
            data: {
              removeFileAccessesForContents: registry.handleRemoveFileAccesses(
                body.variables.fileAccesses,
              ),
            },
          });
        }
        return JSON.stringify({ data: {} });
      },
      { headers: { 'content-type': 'application/json' } },
    )
    .persist();
  
  // Content Upload
  client
    .intercept({
      path: (p) => p.includes('/scoped/upload'),
      method: 'PUT',
    })
    .reply(200, '')
    .persist();
};

export const mockUniqueScopeManagement = (
  agent: MockAgent,
  baseUrl: string,
  registry: FakeUniqueRegistry,
) => {
  const url = new URL(baseUrl);
  const client = agent.get(url.origin);

  client
    .intercept({
      path: (p) => p.includes('/graphql'),
      method: 'POST',
    })
    .reply(
      200,
      (opts) => {
        const body = typeof opts.body === 'string' ? JSON.parse(opts.body) : JSON.parse(opts.body.toString());
        const opName = body.query.match(/(?:query|mutation)\s+(\w+)/)?.[1] || body.operationName;
        
        if (opName === 'CreateScopeAccesses' || body.query.includes('mutation CreateScopeAccesses')) {
          return JSON.stringify({
            data: {
              createScopeAccesses: true,
            },
          });
        }
        if (opName === 'DeleteScopeAccesses' || body.query.includes('mutation DeleteScopeAccesses')) {
          return JSON.stringify({
            data: {
              deleteScopeAccesses: true,
            },
          });
        }
        if (opName === 'User' || body.query.includes('query User')) {
          return JSON.stringify({
            data: {
              me: {
                user: {
                  id: 'fake-user-id',
                },
              },
            },
          });
        }
        if (opName === 'ListUsers' || body.query.includes('query ListUsers')) {
          return JSON.stringify({
            data: {
              listUsers: {
                totalCount: 3,
                nodes: [
                  {
                    id: 'id-perm-1',
                    active: true,
                    email: 'user@example.com',
                  },
                  {
                    id: 'id-user-perm',
                    active: true,
                    email: 'other-user@example.com',
                  },
                  {
                    id: 'fake-user-id',
                    active: true,
                    email: 'service-user@example.com',
                  }
                ],
              },
            },
          });
        }
        if (opName === 'ListGroups' || body.query.includes('query ListGroups')) {
          return JSON.stringify({
            data: {
              listGroups: [
                {
                  id: 'id-group-perm',
                  name: 'Finance Group',
                  externalId: `sp-connector:group:11111111-1111-4111-8111-111111111111:id-group-perm`,
                  members: [],
                },
              ],
            },
          });
        }
        if (opName === 'PaginatedScope' || body.query.includes('query PaginatedScope')) {
          const id = body.variables.where?.id?.equals;
          const parentId = body.variables.where?.parentId?.equals;
          
          let nodes = [];
          if (id) {
            nodes = [{
              id,
              name: 'Default Scope',
              parentId: null,
              externalId: `${EXTERNAL_ID_PREFIX}site:11111111-1111-4111-8111-111111111111`,
            }];
          } else if (parentId) {
            nodes = [];
          }

          return JSON.stringify({
            data: {
              paginatedScope: {
                totalCount: nodes.length,
                nodes,
              },
            },
          });
        }
        if (opName === 'UpdateScope' || body.query.includes('mutation UpdateScope')) {
          return JSON.stringify({
            data: {
              updateScope: {
                id: body.variables.id,
                name: 'Updated Scope',
                externalId: body.variables.input.externalId,
              },
            },
          });
        }
        if (opName === 'GenerateScopesBasedOnPaths' || body.query.includes('mutation GenerateScopesBasedOnPaths')) {
          return JSON.stringify({
            data: {
              generateScopesBasedOnPaths: body.variables.paths.map((path: string, i: number) => ({
                id: `scope-${path.replace(/\//g, '-')}`,
                name: path.split('/').pop() || 'root',
                parentId: 'parent-id',
                externalId: null,
              })),
            },
          });
        }
        if (opName === 'CreateGroup' || body.query.includes('mutation CreateGroup')) {
          return JSON.stringify({
            data: {
              createGroup: {
                id: 'id-group-perm',
                name: body.variables.name,
                externalId: body.variables.externalId,
              },
            },
          });
        }
        if (opName === 'AddGroupMembers' || body.query.includes('mutation AddGroupMembers')) {
          return JSON.stringify({
            data: {
              createMemberships: body.variables.userIds.map((userId: string) => ({
                entityId: userId,
                groupId: body.variables.groupId,
              })),
            },
          });
        }
        return JSON.stringify({ data: {} });
      },
      { headers: { 'content-type': 'application/json' } },
    )
    .persist();
};

export interface MockGraphState {
  drives: any[];
  itemsByDrive: Record<string, any[]>;
  permissionsByItem: Record<string, any[]>;
  siteLists: any[];
  listItems: Record<string, any[]>;
  pageContent: Record<string, any>;
}

export const mockGraphApi = (agent: MockAgent, state: MockGraphState) => {
  const client = agent.get('https://graph.microsoft.com');

  // Drives
  client
    .intercept({
      path: (p) => p.includes('/drives') && !p.includes('/items'),
      method: 'GET',
    })
    .reply(200, (opts) => {
      return JSON.stringify({ value: state.drives });
    }, { headers: { 'content-type': 'application/json' } })
    .persist();

  // Drive Items
  client
    .intercept({
      path: (p) => p.includes('/items') && p.includes('/children'),
      method: 'GET',
    })
    .reply(200, (opts) => {
      const match = opts.path.match(/\/drives\/(.*)\/items\/(.*)\/children/);
      const driveId = match?.[1];
      const items = driveId ? (state.itemsByDrive[driveId] || []) : [];
      return JSON.stringify({ value: items });
    }, { headers: { 'content-type': 'application/json' } })
    .persist();

  // Permissions
  client
    .intercept({
      path: (p) => p.includes('/permissions'),
      method: 'GET',
    })
    .reply(200, (opts) => {
      const match = opts.path.match(/\/items\/(.*)\/permissions/);
      const itemId = match?.[1];
      const perms = itemId ? (state.permissionsByItem[itemId] || []) : [];
      return JSON.stringify({ value: perms });
    }, { headers: { 'content-type': 'application/json' } })
    .persist();

  // Site Lists
  client
    .intercept({
      path: (p) => p.includes('/lists') && !p.includes('/items'),
      method: 'GET',
    })
    .reply(200, (opts) => {
      return JSON.stringify({ value: state.siteLists });
    }, { headers: { 'content-type': 'application/json' } })
    .persist();

  // List Items
  client
    .intercept({
      path: (p) => p.includes('/lists/') && p.includes('/items') && !p.match(/\/items\/[^/?]+\/?(\?|$)/),
      method: 'GET',
    })
    .reply(200, (opts) => {
      const match = opts.path.match(/\/lists\/(.*)\/items/);
      const listId = match?.[1];
      const items = listId ? (state.listItems[listId] || []) : [];
      return JSON.stringify({ value: items });
    }, { headers: { 'content-type': 'application/json' } })
    .persist();

  // Site Page Content
  client
    .intercept({
      path: (p) => p.includes('/items/'), // Simplified for better matching
      method: 'GET',
    })
    .reply(200, (opts) => {
      const match = opts.path.match(/\/items\/([^/?]+)/);
      const itemId = match?.[1];
      const content = itemId ? (state.pageContent[itemId] || {}) : {};
      return JSON.stringify(content);
    }, { headers: { 'content-type': 'application/json' } })
    .persist();

  // File Content
  client
    .intercept({
      path: (p) => p.includes('/content'),
      method: 'GET',
    })
    .reply(200, (opts) => {
      return 'mock-file-content';
    })
    .persist();

  // Site Web Url
  client
    .intercept({
      path: (p) => p.includes('/sites/') && !p.includes('/lists') && !p.includes('/drives'),
      method: 'GET',
    })
    .reply(200, (opts) => {
      return JSON.stringify({ webUrl: 'https://sharepoint.example.com/sites/TestSite' });
    }, { headers: { 'content-type': 'application/json' } })
    .persist();

  // Group Members
  client
    .intercept({
      path: (p) => p.includes('/groups/') && p.includes('/members'),
      method: 'GET',
    })
    .reply(200, (opts) => {
      return JSON.stringify({ 
        value: [{
          '@odata.type': '#microsoft.graph.user',
          id: 'user-id-1',
          displayName: 'User One',
          mail: 'user@example.com'
        }] 
      });
    }, { headers: { 'content-type': 'application/json' } })
    .persist();

  // Group Owners
  client
    .intercept({
      path: (p) => p.includes('/groups/') && p.includes('/owners'),
      method: 'GET',
    })
    .reply(200, (opts) => {
      return JSON.stringify({ value: [] });
    }, { headers: { 'content-type': 'application/json' } })
    .persist();
};
