import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { buildSchema, type DocumentNode, type GraphQLSchema, parse, validate } from 'graphql';
import type { RequestDocument, Variables } from 'graphql-request';
import { vi } from 'vitest';
import {
  createDefaultUniqueOperationHandlers,
  type UniqueOperationHandlers,
} from './unique-mock.handlers';
import {
  createUniqueMockStore,
  resetUniqueMockStore,
  seedUniqueMockStore,
  type UniqueMockSeedState,
  type UniqueMockStore,
} from './unique-mock.store';

export type UniqueMockTarget = 'ingestion' | 'scopeManagement';

export interface UniqueStatefulMock {
  ingestionClient: { request: ReturnType<typeof vi.fn> };
  scopeManagementClient: { request: ReturnType<typeof vi.fn> };
  store: UniqueMockStore;
  seed: (seedState: UniqueMockSeedState) => void;
  reset: () => void;
}

export interface CreateUniqueStatefulMockOptions {
  ingestionSchemaPath?: string;
  scopeManagementSchemaPath?: string;
  handlers?: UniqueOperationHandlers;
  initialState?: UniqueMockSeedState;
}

export function createUniqueStatefulMock(
  options: CreateUniqueStatefulMockOptions = {},
): UniqueStatefulMock {
  const initialState = options.initialState;
  const ingestionSchema = loadSchemaFromSdl(
    options.ingestionSchemaPath ?? defaultSchemaPath('node-ingestion.schema.graphql'),
  );
  const scopeManagementSchema = loadSchemaFromSdl(
    options.scopeManagementSchemaPath ?? defaultSchemaPath('node-scope-management.schema.graphql'),
  );

  const store = createUniqueMockStore();
  const handlers = options.handlers ?? createDefaultUniqueOperationHandlers();

  seedUniqueMockStore(store, defaultSeedState());
  if (initialState) seedUniqueMockStore(store, initialState);

  const ingestionClient = {
    request: vi.fn(
      async <T, V extends Variables = Variables>(
        document: RequestDocument,
        variables?: V,
      ): Promise<T> => {
        return await handleRequest<T>({
          target: 'ingestion',
          schema: ingestionSchema,
          handlers,
          store,
          document,
          variables,
        });
      },
    ),
  };

  const scopeManagementClient = {
    request: vi.fn(
      async <T, V extends Variables = Variables>(
        document: RequestDocument,
        variables?: V,
      ): Promise<T> => {
        return await handleRequest<T>({
          target: 'scopeManagement',
          schema: scopeManagementSchema,
          handlers,
          store,
          document,
          variables,
        });
      },
    ),
  };

  return {
    ingestionClient,
    scopeManagementClient,
    store,
    seed: (seedState) => seedUniqueMockStore(store, seedState),
    reset: () => {
      resetUniqueMockStore(store);
      seedUniqueMockStore(store, defaultSeedState());
      if (initialState) seedUniqueMockStore(store, initialState);
    },
  };
}

function loadSchemaFromSdl(schemaPath: string): GraphQLSchema {
  const sdl = readFileSync(schemaPath, 'utf8');
  return buildSchema(sdl);
}

function defaultSchemaPath(filename: string): string {
  // Use cwd-based resolution to avoid module-system differences (__dirname / ESM) under Vitest/SWC.
  // When running `pnpm -C services/sharepoint-connector test`, `process.cwd()` is the package root.
  return resolve(process.cwd(), 'test', 'unique-schema', filename);
}

async function handleRequest<T>(input: {
  target: UniqueMockTarget;
  schema: GraphQLSchema;
  handlers: UniqueOperationHandlers;
  store: UniqueMockStore;
  document: RequestDocument;
  variables?: Variables;
}): Promise<T> {
  const source = toDocumentSource(input.document);
  const ast = parse(source);
  const operationName = extractOperationNameFromAst(ast);

  const validationErrors = validate(input.schema, ast);
  if (validationErrors.length > 0) {
    const printable = validationErrors.map((e) => e.message).join('\n');
    throw new Error(
      `Unique mock GraphQL validation failed (${input.target}:${operationName}).\n${printable}`,
    );
  }

  const handler = input.handlers[operationName];
  if (!handler) {
    throw new Error(
      `Unique mock has no handler for operation "${operationName}" (target: ${input.target}). ` +
        `Add it in test utils unique-stateful-mock handlers.`,
    );
  }

  const result = handler({
    operationName,
    variables: input.variables ?? {},
    store: input.store,
  });

  return result as T;
}

function toDocumentSource(document: RequestDocument): string {
  if (typeof document === 'string') return document;

  const maybeDoc = document as unknown as { loc?: { source: { body: string } } };
  const body = maybeDoc.loc?.source?.body;
  if (typeof body === 'string' && body.length > 0) return body;

  const asString = document.toString();
  if (!asString || asString === '[object Object]') {
    throw new Error('Unique mock received a non-string GraphQL document without loc.source.body');
  }
  return asString;
}

function extractOperationNameFromAst(ast: DocumentNode): string {
  const op = ast.definitions.find((d) => d.kind === 'OperationDefinition');
  if (op?.kind === 'OperationDefinition' && op.name?.value) return op.name.value;
  return 'unknown';
}

function defaultSeedState(): UniqueMockSeedState {
  return {
    users: [
      {
        id: 'unique-user-1',
        email: 'user@example.com',
        active: true,
      },
    ],
    scopes: [
      {
        id: 'scope_root_1',
        name: 'RootScope',
        parentId: null,
        externalId: null,
      },
    ],
  };
}
