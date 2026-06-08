/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */

import { sql } from 'drizzle-orm';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { McpProcessesHealthIndicator } from './mcp-processes-health.indicator';

const MOCK_SUBQUERY = sql`SELECT user_profile_id FROM inbox_configurations`;

const INGESTION_UNIQUEAPI = {
  mcpBackend: 'microsoft_graph_and_unique_api',
  syncFailureThreshold: 0.15,
} as any;
const INGESTION_GRAPH = { mcpBackend: 'microsoft_graph', connectivityTimeoutMs: 3000 } as any;
const DELEGATED_ENABLED = {
  scan: 'fullAccessOnly',
  stalenessThresholdHours: 24,
  failureThreshold: 0.15,
} as any;
const DELEGATED_DISABLED = { scan: 'disabled' } as any;

function createHealthIndicatorService() {
  return {
    check: vi.fn((key: string) => ({
      up: vi.fn((details?: object) => ({ [key]: { status: 'up', ...details } })),
      down: vi.fn((details?: object) => ({ [key]: { status: 'down', ...details } })),
    })),
  };
}

function createMockDb(selectRow: object) {
  return {
    selectDistinct: vi.fn().mockReturnValue({
      from: vi.fn().mockReturnValue({
        innerJoin: vi.fn().mockReturnValue({
          innerJoin: vi.fn().mockReturnValue(MOCK_SUBQUERY),
        }),
      }),
    }),
    select: vi.fn().mockReturnValue({
      from: vi.fn().mockReturnValue({
        where: vi.fn().mockResolvedValue([selectRow]),
      }),
    }),
  };
}

function createIndicator(
  db: any,
  ingestionCfg: any,
  delegatedAccessCfg: any,
  healthIndicatorService = createHealthIndicatorService(),
) {
  return new McpProcessesHealthIndicator(
    db,
    ingestionCfg,
    delegatedAccessCfg,
    healthIndicatorService as any,
  );
}

describe('McpProcessesHealthIndicator', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('checkFullSync', () => {
    it('returns up when there are no eligible users', async () => {
      const db = createMockDb({ totalEligible: 0, failing: 0 });
      const indicator = createIndicator(db, INGESTION_UNIQUEAPI, DELEGATED_DISABLED);

      const result = await indicator.checkFullSync('fullSync');

      expect(result).toMatchObject({ fullSync: { status: 'up' } });
    });

    it('returns up when failing users are below threshold', async () => {
      const db = createMockDb({ totalEligible: 100, failing: 14 });
      const indicator = createIndicator(db, INGESTION_UNIQUEAPI, DELEGATED_DISABLED);

      const result = await indicator.checkFullSync('fullSync');

      expect(result).toMatchObject({ fullSync: { status: 'up' } });
    });

    it('returns down when failing users are above threshold', async () => {
      const db = createMockDb({ totalEligible: 100, failing: 20 });
      const indicator = createIndicator(db, INGESTION_UNIQUEAPI, DELEGATED_DISABLED);

      const result = await indicator.checkFullSync('fullSync');

      expect(result).toMatchObject({ fullSync: { status: 'down' } });
    });

    it('throws when called with MicrosoftGraph ingestion config', async () => {
      const db = createMockDb({ totalEligible: 0, failing: 0 });
      const indicator = createIndicator(db, INGESTION_GRAPH, DELEGATED_DISABLED);

      await expect(indicator.checkFullSync('fullSync')).rejects.toThrow();
    });
  });

  describe('checkLiveCatchup', () => {
    it('returns up when there are no eligible users', async () => {
      const db = createMockDb({ totalEligible: 0, failing: 0 });
      const indicator = createIndicator(db, INGESTION_UNIQUEAPI, DELEGATED_DISABLED);

      const result = await indicator.checkLiveCatchup('liveCatchup');

      expect(result).toMatchObject({ liveCatchup: { status: 'up' } });
    });

    it('returns up when failing users are below threshold', async () => {
      const db = createMockDb({ totalEligible: 100, failing: 14 });
      const indicator = createIndicator(db, INGESTION_UNIQUEAPI, DELEGATED_DISABLED);

      const result = await indicator.checkLiveCatchup('liveCatchup');

      expect(result).toMatchObject({ liveCatchup: { status: 'up' } });
    });

    it('returns down when failing users are above threshold', async () => {
      const db = createMockDb({ totalEligible: 100, failing: 20 });
      const indicator = createIndicator(db, INGESTION_UNIQUEAPI, DELEGATED_DISABLED);

      const result = await indicator.checkLiveCatchup('liveCatchup');

      expect(result).toMatchObject({ liveCatchup: { status: 'down' } });
    });

    it('throws when called with MicrosoftGraph ingestion config', async () => {
      const db = createMockDb({ totalEligible: 0, failing: 0 });
      const indicator = createIndicator(db, INGESTION_GRAPH, DELEGATED_DISABLED);

      await expect(indicator.checkLiveCatchup('liveCatchup')).rejects.toThrow();
    });
  });

  describe('checkDelegatedAccess', () => {
    it('returns up when there are no eligible delegated users', async () => {
      const db = createMockDb({ totalDelegated: 0, stale: 0 });
      const indicator = createIndicator(db, INGESTION_GRAPH, DELEGATED_ENABLED);

      const result = await indicator.checkDelegatedAccess('delegatedAccess');

      expect(result).toMatchObject({ delegatedAccess: { status: 'up' } });
    });

    it('returns up when stale users are below threshold', async () => {
      const db = createMockDb({ totalDelegated: 100, stale: 14 });
      const indicator = createIndicator(db, INGESTION_GRAPH, DELEGATED_ENABLED);

      const result = await indicator.checkDelegatedAccess('delegatedAccess');

      expect(result).toMatchObject({ delegatedAccess: { status: 'up' } });
    });

    it('returns down when stale users are above threshold', async () => {
      const db = createMockDb({ totalDelegated: 100, stale: 20 });
      const indicator = createIndicator(db, INGESTION_GRAPH, DELEGATED_ENABLED);

      const result = await indicator.checkDelegatedAccess('delegatedAccess');

      expect(result).toMatchObject({ delegatedAccess: { status: 'down' } });
    });

    it('throws when called with disabled delegated access config', async () => {
      const db = createMockDb({ totalDelegated: 0, stale: 0 });
      const indicator = createIndicator(db, INGESTION_GRAPH, DELEGATED_DISABLED);

      await expect(indicator.checkDelegatedAccess('delegatedAccess')).rejects.toThrow();
    });
  });
});
