import { PgDialect } from 'drizzle-orm/pg-core';
import { describe, expect, it } from 'vitest';
import { sourceOnListedMailboxConflict, sourceOnLoginConflict } from '../user-profiles.table';

const dialect = new PgDialect();

describe('sourceOnListedMailboxConflict', () => {
  it('upgrades from the existing row token, not from excluded', () => {
    const { sql: query } = dialect.sqlToQuery(sourceOnListedMailboxConflict);

    expect(query).toContain('shared-mailbox-with-login');
    expect(query).toContain('access_token');
    expect(query).toContain('IS NOT NULL');
    expect(query).not.toContain('excluded');
  });
});

describe('sourceOnLoginConflict', () => {
  it('upgrades shared-mailbox regardless of stored token and leaves oauth unchanged', () => {
    const { sql: query } = dialect.sqlToQuery(sourceOnLoginConflict);

    expect(query).toContain("'shared-mailbox'");
    expect(query).toContain("'shared-mailbox-with-login'");
    expect(query).not.toContain('access_token');
    expect(query).not.toContain("'oauth'");
  });
});
