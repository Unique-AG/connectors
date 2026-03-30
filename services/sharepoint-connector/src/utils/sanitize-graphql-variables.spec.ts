import { beforeEach, describe, expect, it } from 'vitest';
import { LogsDiagnosticDataPolicy } from '../config/app.config';
import { sanitizeGraphqlVariables } from './sanitize-graphql-variables';

describe('sanitizeGraphqlVariables', () => {
  beforeEach(() => {
    process.env.LOGS_DIAGNOSTICS_DATA_POLICY = LogsDiagnosticDataPolicy.CONCEAL;
  });

  it('returns undefined for undefined variables', () => {
    expect(sanitizeGraphqlVariables(undefined, [])).toBeUndefined();
  });

  it('returns variables as-is when smearing is disabled (disclose policy)', () => {
    process.env.LOGS_DIAGNOSTICS_DATA_POLICY = LogsDiagnosticDataPolicy.DISCLOSE;

    const variables = {
      input: { title: 'secret-doc.docx', mimeType: 'application/pdf' },
      scopeId: 'scope-123',
    };

    expect(sanitizeGraphqlVariables(variables, ['scopeId'])).toEqual(variables);
  });

  it('keeps whitelisted top-level string values as-is', () => {
    const variables = { scopeId: 'scope-123', sourceKind: 'sharepoint' };
    const result = sanitizeGraphqlVariables(variables, ['scopeId', 'sourceKind']);

    expect(result).toEqual({ scopeId: 'scope-123', sourceKind: 'sharepoint' });
  });

  it('smears non-whitelisted string values', () => {
    const variables = { title: 'secret-document.docx', scopeId: 'scope-123' };
    const result = sanitizeGraphqlVariables(variables, ['scopeId']);

    expect(result?.scopeId).toBe('scope-123');
    expect(result?.title).not.toBe('secret-document.docx');
    expect(result?.title).toContain('*');
  });

  it('keeps whitelisted nested values via dot-paths', () => {
    const variables = {
      input: {
        title: 'secret-doc.docx',
        mimeType: 'application/pdf',
        key: 'sites/abc/secret-doc.docx',
      },
    };
    const result = sanitizeGraphqlVariables(variables, ['input.mimeType']);

    expect((result?.input as Record<string, unknown>).mimeType).toBe('application/pdf');
    expect((result?.input as Record<string, unknown>).title).toContain('*');
    expect((result?.input as Record<string, unknown>).key).toContain('*');
  });

  it('preserves numbers and booleans without smearing', () => {
    const variables = {
      storeInternally: true,
      input: { byteSize: 1234 },
      secretString: 'password',
    };
    const result = sanitizeGraphqlVariables(variables, []);

    expect(result?.storeInternally).toBe(true);
    expect((result?.input as Record<string, unknown>).byteSize).toBe(1234);
    expect(result?.secretString).toContain('*');
  });

  it('smears all elements in a non-whitelisted array', () => {
    const variables = {
      fileAccess: ['u:user123R', 'u:user456W'],
    };
    const result = sanitizeGraphqlVariables(variables, []);

    const arr = result?.fileAccess as string[];
    expect(arr).toHaveLength(2);
    for (const item of arr) {
      expect(item).toContain('*');
    }
  });

  it('keeps array elements as-is when the array path is whitelisted', () => {
    const variables = {
      contentIds: ['id-1', 'id-2', 'id-3'],
    };
    const result = sanitizeGraphqlVariables(variables, ['contentIds']);

    expect(result?.contentIds).toEqual(['id-1', 'id-2', 'id-3']);
  });

  it('handles deeply nested objects', () => {
    const variables = {
      where: {
        externalId: { startsWith: 'spc:folder:site-123/' },
      },
      skip: 0,
      take: 100,
    };
    const result = sanitizeGraphqlVariables(variables, ['skip', 'take']);

    expect(result?.skip).toBe(0);
    expect(result?.take).toBe(100);
    const where = result?.where as Record<string, Record<string, string>>;
    expect(where.externalId.startsWith).toContain('*');
  });

  it('smears all leaves when no logSafeKeys are provided', () => {
    const variables = {
      input: { title: 'my-file.txt', key: 'some/path' },
      scopeId: 'scope-1',
    };
    const result = sanitizeGraphqlVariables(variables, undefined);
    const input = result?.input as Record<string, string>;

    expect(input.title).toContain('*');
    expect(input.key).toContain('*');
    expect(result?.scopeId).toContain('*');
  });

  it('handles null values without error', () => {
    const variables = { key: null as unknown as string, name: 'test-name' };
    const result = sanitizeGraphqlVariables(variables, ['key']);

    expect(result?.key).toBeNull();
    expect(result?.name).toContain('*');
  });

  it('handles objects inside arrays', () => {
    const variables = {
      scopeAccesses: [
        { accessType: 'READ', entityId: 'user-123', entityType: 'USER' },
        { accessType: 'WRITE', entityId: 'user-456', entityType: 'USER' },
      ],
    };
    const result = sanitizeGraphqlVariables(variables, [
      'scopeAccesses.accessType',
      'scopeAccesses.entityType',
    ]);

    const accesses = result?.scopeAccesses as Array<Record<string, string>>;
    expect(accesses[0].accessType).toBe('READ');
    expect(accesses[0].entityType).toBe('USER');
    expect(accesses[0].entityId).toContain('*');
    expect(accesses[1].accessType).toBe('WRITE');
    expect(accesses[1].entityId).toContain('*');
  });

  it('returns an empty object for empty variables', () => {
    const result = sanitizeGraphqlVariables({}, ['anything']);
    expect(result).toEqual({});
  });

  it('smears empty string values (not whitelisted)', () => {
    const result = sanitizeGraphqlVariables({ name: '' }, []);
    expect(result?.name).toBe('[Smeared]');
  });

  it('preserves empty string values when whitelisted', () => {
    const result = sanitizeGraphqlVariables({ name: '' }, ['name']);
    expect(result?.name).toBe('');
  });

  it('handles nested arrays of objects', () => {
    const variables = {
      groups: [
        {
          members: [
            { entityId: 'user-abc-1234', role: 'admin' },
            { entityId: 'user-def-5678', role: 'viewer' },
          ],
        },
      ],
    };
    const result = sanitizeGraphqlVariables(variables, ['groups.members.role']);

    const groups = result?.groups as Array<Record<string, Array<Record<string, string>>>>;
    expect(groups[0].members[0].role).toBe('admin');
    expect(groups[0].members[0].entityId).toContain('*');
    expect(groups[0].members[1].role).toBe('viewer');
    expect(groups[0].members[1].entityId).toContain('*');
  });

  it('handles query-style variables (no mutation)', () => {
    const variables = {
      where: { scopeId: { equals: 'scope-1' } },
      skip: 0,
      take: 50,
    };
    const result = sanitizeGraphqlVariables(variables, ['where.scopeId.equals', 'skip', 'take']);

    expect(result?.skip).toBe(0);
    expect(result?.take).toBe(50);
    const where = result?.where as Record<string, Record<string, string>>;
    expect(where.scopeId.equals).toBe('scope-1');
  });

  it('matches the ContentUpsert use case end-to-end', () => {
    const variables = {
      input: {
        key: 'site-123/drives/abc/secret-report.docx',
        title: 'Secret Report Q4.docx',
        mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        ownerType: 'Scope',
        url: 'https://tenant.sharepoint.com/sites/team/Shared%20Documents/Secret%20Report.docx',
        byteSize: 45678,
        metadata: {
          Filename: 'Secret Report Q4.docx',
          Path: '/sites/team/Shared Documents',
          Author: { email: 'john@example.com', displayName: 'John Smith', id: 'user-789' },
        },
      },
      scopeId: 'scope-abc',
      sourceOwnerType: 'Company',
      sourceKind: 'sharepoint',
      sourceName: 'sharepoint-connector',
      storeInternally: true,
      baseUrl: 'https://tenant.sharepoint.com',
    };

    const logSafeKeys = [
      'scopeId',
      'sourceOwnerType',
      'sourceKind',
      'sourceName',
      'storeInternally',
      'input.mimeType',
      'input.ownerType',
      'input.byteSize',
    ];

    const result = sanitizeGraphqlVariables(variables, logSafeKeys);
    const input = result?.input as Record<string, unknown>;
    const metadata = input.metadata as Record<string, unknown>;
    const author = metadata.Author as Record<string, string>;

    // Whitelisted fields preserved
    expect(result?.scopeId).toBe('scope-abc');
    expect(result?.sourceKind).toBe('sharepoint');
    expect(result?.sourceName).toBe('sharepoint-connector');
    expect(result?.storeInternally).toBe(true);
    expect(input.mimeType).toBe(
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    );
    expect(input.ownerType).toBe('Scope');
    expect(input.byteSize).toBe(45678);

    // Sensitive fields smeared
    expect(input.key).toContain('*');
    expect(input.title).toContain('*');
    expect(input.url).toContain('*');
    expect(result?.baseUrl).toContain('*');
    expect(metadata.Filename).toContain('*');
    expect(metadata.Path).toContain('*');
    expect(author.email).toContain('*');
    expect(author.displayName).toContain('*');

    // Original variable names should not appear as full strings
    expect(JSON.stringify(result)).not.toContain('Secret Report Q4.docx');
    expect(JSON.stringify(result)).not.toContain('john@example.com');
    expect(JSON.stringify(result)).not.toContain('John Smith');
  });
});
