export const RESOURCE_NAMES = [
  'relationships',
  'coverageAssignments',
  'contacts',
  'subscriptions',
  'diligence',
  'tasks',
  'activities',
  'outlookTasks',
  'calendarEvents',
  'messages',
] as const;

export type ResourceName = (typeof RESOURCE_NAMES)[number];

export interface DemoRecord {
  resource: ResourceName;
  id: string;
  relationshipId: string | null;
  data: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface SeedRecord {
  resource: ResourceName;
  id: string;
  relationshipId: string | null;
  data: Record<string, unknown>;
}

export interface SeedData {
  snapshotDate: string;
  records: SeedRecord[];
}

export interface RecordInput {
  id?: string;
  relationshipId?: string | null;
  data: Record<string, unknown>;
}

export const isResourceName = (value: string): value is ResourceName =>
  RESOURCE_NAMES.some((resource) => resource === value);
