import assert from 'node:assert/strict';
import { rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { Injectable, OnModuleDestroy } from '@nestjs/common';
import {
  DemoRecord,
  RESOURCE_NAMES,
  RecordInput,
  ResourceName,
  SeedData,
  SeedRecord,
} from './demo-record';
import seedDataJson from './seed-data.json';

interface DatabaseRow {
  resource: string;
  id: string;
  relationship_id: string | null;
  data: string;
  created_at: string;
  updated_at: string;
}

const seedData = seedDataJson as SeedData;
const DAY_IN_MILLISECONDS = 24 * 60 * 60 * 1000;
const CURATED_PREVIOUS_WEEK_DATE = '2026-07-24';
const BUSINESS_DATE_FIELDS = new Set([
  'date',
  'assignedDate',
  'initialSubscriptionDate',
  'sentDate',
  'dueDate',
  'completedDate',
  'lastCompletedDate',
  'targetCompletionDate',
  'lastContactDate',
  'nextTouchpointDate',
]);

const parseCalendarDate = (value: string): number | undefined => {
  const datePrefix = value.slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(datePrefix)) {
    return undefined;
  }

  const timestamp = Date.parse(`${datePrefix}T00:00:00.000Z`);
  if (Number.isNaN(timestamp) || new Date(timestamp).toISOString().slice(0, 10) !== datePrefix) {
    return undefined;
  }
  return timestamp;
};

const currentIsoWeekWednesday = (now: Date): string => {
  const isoDay = now.getUTCDay() || 7;
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 3 - isoDay))
    .toISOString()
    .slice(0, 10);
};

const shiftDateValue = (value: unknown, dayDelta: number): unknown => {
  if (typeof value !== 'string') {
    return value;
  }

  const timestamp = parseCalendarDate(value);
  if (timestamp === undefined) {
    return value;
  }

  const shiftedPrefix = new Date(timestamp + dayDelta * DAY_IN_MILLISECONDS)
    .toISOString()
    .slice(0, 10);
  return `${shiftedPrefix}${value.slice(10)}`;
};

const shiftBusinessDates = (
  value: unknown,
  dayDelta: number,
  curatePreviousWeekDate: boolean,
): unknown => {
  if (Array.isArray(value)) {
    return value.map((item) => shiftBusinessDates(item, dayDelta, curatePreviousWeekDate));
  }
  if (typeof value !== 'object' || value === null) {
    return value;
  }

  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => {
      if (!BUSINESS_DATE_FIELDS.has(key)) {
        return [key, shiftBusinessDates(item, dayDelta, curatePreviousWeekDate)];
      }

      const curatedDayDelta =
        curatePreviousWeekDate &&
        key === 'date' &&
        typeof item === 'string' &&
        item.slice(0, 10) === CURATED_PREVIOUS_WEEK_DATE
          ? dayDelta - 7
          : dayDelta;
      return [key, shiftDateValue(item, curatedDayDelta)];
    }),
  );
};

const isIdentifierRow = (value: unknown): value is { id: string } =>
  typeof value === 'object' && value !== null && 'id' in value && typeof value.id === 'string';

const isCountRow = (value: unknown): value is { count: number } =>
  typeof value === 'object' &&
  value !== null &&
  'count' in value &&
  typeof value.count === 'number';

const isDatabaseRow = (value: unknown): value is DatabaseRow => {
  if (typeof value !== 'object' || value === null) {
    return false;
  }

  const row = value as Partial<DatabaseRow>;
  return (
    typeof row.resource === 'string' &&
    typeof row.id === 'string' &&
    (typeof row.relationship_id === 'string' || row.relationship_id === null) &&
    typeof row.data === 'string' &&
    typeof row.created_at === 'string' &&
    typeof row.updated_at === 'string'
  );
};

const toRecord = (value: unknown): DemoRecord => {
  assert.ok(isDatabaseRow(value), 'SQLite returned an invalid demo record');
  assert.ok(
    RESOURCE_NAMES.some((resource) => resource === value.resource),
    `Unknown resource "${value.resource}" in SQLite`,
  );

  const data = JSON.parse(value.data) as unknown;
  assert.ok(typeof data === 'object' && data !== null && !Array.isArray(data));

  return {
    resource: value.resource as ResourceName,
    id: value.id,
    relationshipId: value.relationship_id,
    data: data as Record<string, unknown>,
    createdAt: value.created_at,
    updatedAt: value.updated_at,
  };
};

@Injectable()
export class DemoRepository implements OnModuleDestroy {
  private readonly database: DatabaseSync;
  public snapshotDate = seedData.snapshotDate;

  public constructor() {
    const databasePath = process.env.DEMO_DB_PATH ?? join(tmpdir(), 'demo-ir-mcp.sqlite');
    if (databasePath !== ':memory:') {
      rmSync(databasePath, { force: true });
      rmSync(`${databasePath}-shm`, { force: true });
      rmSync(`${databasePath}-wal`, { force: true });
    }

    this.database = new DatabaseSync(databasePath);
    this.database.exec(`
      PRAGMA journal_mode = WAL;
      PRAGMA foreign_keys = ON;
      CREATE TABLE records (
        resource TEXT NOT NULL,
        id TEXT NOT NULL,
        relationship_id TEXT,
        data TEXT NOT NULL CHECK (json_valid(data)),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (resource, id)
      );
      CREATE INDEX records_relationship_idx
        ON records (relationship_id, resource);
    `);
    this.reset();
  }

  public onModuleDestroy(): void {
    this.database.close();
  }

  public list(resource: ResourceName, relationshipId?: string): DemoRecord[] {
    const statement =
      relationshipId === undefined
        ? this.database.prepare(
            `SELECT resource, id, relationship_id, data, created_at, updated_at
             FROM records WHERE resource = ? ORDER BY id`,
          )
        : this.database.prepare(
            `SELECT resource, id, relationship_id, data, created_at, updated_at
             FROM records WHERE resource = ? AND relationship_id = ? ORDER BY id`,
          );
    const rows =
      relationshipId === undefined
        ? statement.all(resource)
        : statement.all(resource, relationshipId);
    return rows.map(toRecord);
  }

  public listAll(): DemoRecord[] {
    return this.database
      .prepare(
        `SELECT resource, id, relationship_id, data, created_at, updated_at
         FROM records ORDER BY resource, id`,
      )
      .all()
      .map(toRecord);
  }

  public get(resource: ResourceName, id: string): DemoRecord | undefined {
    const row = this.database
      .prepare(
        `SELECT resource, id, relationship_id, data, created_at, updated_at
         FROM records WHERE resource = ? AND id = ?`,
      )
      .get(resource, id);
    return row === undefined ? undefined : toRecord(row);
  }

  public create(resource: ResourceName, input: RecordInput): DemoRecord {
    this.database.exec('BEGIN IMMEDIATE');
    try {
      const explicitId = input.id?.trim();
      const relationshipId = resource === 'relationships' ? null : (input.relationshipId ?? null);
      const id = explicitId ?? this.allocateId(resource, input.data, relationshipId);
      const data = this.withBusinessId(resource, id, input.data);
      const now = new Date().toISOString();
      this.database
        .prepare(
          `INSERT INTO records
            (resource, id, relationship_id, data, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)`,
        )
        .run(resource, id, relationshipId, JSON.stringify(data), now, now);

      const created = this.get(resource, id);
      assert.ok(created, `Created ${resource} record "${id}" was not found`);
      this.database.exec('COMMIT');
      return created;
    } catch (error) {
      this.database.exec('ROLLBACK');
      throw error;
    }
  }

  public update(resource: ResourceName, id: string, input: RecordInput): DemoRecord | undefined {
    const existing = this.get(resource, id);
    if (!existing) {
      return undefined;
    }

    const relationshipId =
      resource === 'relationships'
        ? null
        : input.relationshipId === undefined
          ? existing.relationshipId
          : input.relationshipId;
    const data = this.withBusinessId(resource, id, { ...existing.data, ...input.data });
    const updatedAt = new Date().toISOString();
    this.database
      .prepare(
        `UPDATE records
         SET relationship_id = ?, data = ?, updated_at = ?
         WHERE resource = ? AND id = ?`,
      )
      .run(relationshipId ?? null, JSON.stringify(data), updatedAt, resource, id);

    const updated = this.get(resource, id);
    assert.ok(updated, `Updated ${resource} record "${id}" was not found`);
    return updated;
  }

  public delete(resource: ResourceName, id: string): boolean {
    this.database.exec('BEGIN IMMEDIATE');
    try {
      if (resource === 'relationships') {
        this.database
          .prepare("DELETE FROM records WHERE relationship_id = ? AND resource != 'relationships'")
          .run(id);
      }
      const result = this.database
        .prepare('DELETE FROM records WHERE resource = ? AND id = ?')
        .run(resource, id);
      this.database.exec('COMMIT');
      return result.changes > 0;
    } catch (error) {
      this.database.exec('ROLLBACK');
      throw error;
    }
  }

  public reset(): Record<ResourceName, number> {
    const snapshotDate = currentIsoWeekWednesday(new Date());
    const sourceAnchor = parseCalendarDate(seedData.snapshotDate);
    const effectiveAnchor = parseCalendarDate(snapshotDate);
    assert.ok(sourceAnchor !== undefined, 'Seed snapshot date is invalid');
    assert.ok(effectiveAnchor !== undefined, 'Effective snapshot date is invalid');
    const dayDelta = (effectiveAnchor - sourceAnchor) / DAY_IN_MILLISECONDS;
    const now = new Date().toISOString();
    const insert = this.database.prepare(
      `INSERT INTO records
        (resource, id, relationship_id, data, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?)`,
    );

    this.database.exec('BEGIN IMMEDIATE');
    try {
      this.database.exec('DELETE FROM records');
      for (const record of seedData.records) {
        this.insertSeedRecord(insert, record, now, dayDelta);
      }
      this.database.exec('COMMIT');
      this.snapshotDate = snapshotDate;
    } catch (error) {
      this.database.exec('ROLLBACK');
      throw error;
    }

    return Object.fromEntries(
      RESOURCE_NAMES.map((resource) => [resource, this.list(resource).length]),
    ) as Record<ResourceName, number>;
  }

  private insertSeedRecord(
    statement: ReturnType<DatabaseSync['prepare']>,
    record: SeedRecord,
    timestamp: string,
    dayDelta: number,
  ): void {
    const data = shiftBusinessDates(record.data, dayDelta, record.resource === 'calendarEvents');
    statement.run(
      record.resource,
      record.id,
      record.relationshipId,
      JSON.stringify(data),
      timestamp,
      timestamp,
    );
  }

  private allocateId(
    resource: ResourceName,
    data: Record<string, unknown>,
    relationshipId: string | null,
  ): string {
    switch (resource) {
      case 'relationships':
        return data.kind === 'existing'
          ? this.nextCanonicalId(resource, /^LP-(\d+)$/, 'LP-', 3)
          : this.nextCanonicalId(resource, /^P-(\d+)$/, 'P-', 3);
      case 'contacts':
        return this.isProspectRelationship(relationshipId)
          ? this.nextCanonicalId(resource, /^PC-(\d+)$/, 'PC-', 3)
          : this.nextCanonicalId(resource, /^C-(\d+)$/, 'C-', 4);
      case 'activities':
        return this.isProspectRelationship(relationshipId)
          ? this.nextCanonicalId(resource, /^PACT-(\d+)$/, 'PACT-', 4)
          : this.nextCanonicalId(resource, /^ACT-(\d+)$/, 'ACT-', 4);
      case 'tasks':
        return this.nextTaskId();
      case 'coverageAssignments':
        return this.nextCanonicalId(resource, /^COV-(\d+)$/, 'COV-', 4);
      case 'subscriptions':
        return this.nextCanonicalId(resource, /^SUB-(\d+)$/, 'SUB-', 4);
      case 'diligence':
        return this.nextCanonicalId(resource, /^DDQ-(\d+)$/, 'DDQ-', 4);
      case 'calendarEvents':
        return this.nextCanonicalId(resource, /^CAL-(\d+)$/, 'CAL-', 4);
      case 'messages':
        return this.nextCanonicalId(resource, /^MSG-(\d+)$/, 'MSG-', 4);
    }
  }

  private nextCanonicalId(
    resource: ResourceName,
    pattern: RegExp,
    prefix: string,
    width: number,
  ): string {
    const rows = this.database.prepare('SELECT id FROM records WHERE resource = ?').all(resource);
    const maxId = rows.reduce((maximum, row) => {
      assert.ok(isIdentifierRow(row), 'SQLite returned an invalid identifier row');
      const match = pattern.exec(row.id);
      if (!match) {
        return maximum;
      }
      const numericId = Number.parseInt(match[1] ?? '', 10);
      return Number.isNaN(numericId) ? maximum : Math.max(maximum, numericId);
    }, 0);
    return this.nextAvailableId(resource, prefix, width, maxId + 1);
  }

  private nextTaskId(): string {
    const row = this.database
      .prepare("SELECT COUNT(*) AS count FROM records WHERE resource = 'tasks'")
      .get();
    assert.ok(isCountRow(row), 'SQLite returned an invalid task count');
    return this.nextAvailableId('tasks', 'T-', 3, row.count + 1);
  }

  private nextAvailableId(
    resource: ResourceName,
    prefix: string,
    width: number,
    startingNumber: number,
  ): string {
    let numericId = startingNumber;
    let id = `${prefix}${numericId.toString().padStart(width, '0')}`;
    while (this.get(resource, id) !== undefined) {
      numericId += 1;
      id = `${prefix}${numericId.toString().padStart(width, '0')}`;
    }
    return id;
  }

  private isProspectRelationship(relationshipId: string | null): boolean {
    if (relationshipId === null) {
      return false;
    }
    const relationship = this.get('relationships', relationshipId);
    return relationship?.data.kind === 'prospect' || /^P-\d+$/.test(relationshipId);
  }

  private withBusinessId(
    resource: ResourceName,
    id: string,
    data: Record<string, unknown>,
  ): Record<string, unknown> {
    switch (resource) {
      case 'relationships': {
        if (data.kind === 'existing') {
          const lpName = data.lpName ?? data.institution ?? data.name;
          return {
            ...data,
            investorId: id,
            prospectId: undefined,
            institution: undefined,
            ...(lpName === undefined ? {} : { lpName }),
          };
        }
        const institution = data.institution ?? data.lpName ?? data.name;
        return {
          ...data,
          investorId: undefined,
          lpName: undefined,
          prospectId: id,
          ...(institution === undefined ? {} : { institution }),
        };
      }
      case 'contacts':
        return { ...data, contactId: id };
      case 'activities':
        return { ...data, activityId: id };
      case 'tasks':
        return { ...data, taskId: id };
      default:
        return { ...data };
    }
  }
}
