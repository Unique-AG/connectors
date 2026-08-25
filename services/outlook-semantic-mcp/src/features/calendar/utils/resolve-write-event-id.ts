import assert from 'node:assert';

export const SERIES_SCOPES = ['thisOccurrence', 'entireSeries'] as const;
export type SeriesScope = (typeof SERIES_SCOPES)[number];

export type GraphEventType = 'singleInstance' | 'occurrence' | 'exception' | 'seriesMaster';

export function parseGraphEventType(value: string | null | undefined): GraphEventType {
  if (value === 'occurrence' || value === 'exception' || value === 'seriesMaster') {
    return value;
  }
  return 'singleInstance';
}

export function isSeriesOccurrence(type: GraphEventType): boolean {
  return type === 'occurrence' || type === 'exception';
}

export function parseSeriesScope(content: unknown): SeriesScope | undefined {
  if (content === null || typeof content !== 'object' || !('applyTo' in content)) {
    return undefined;
  }
  const applyTo = content.applyTo;
  if (applyTo === 'thisOccurrence' || applyTo === 'entireSeries') {
    return applyTo;
  }
  return undefined;
}

export function resolveWriteEventId(input: {
  eventId: string;
  seriesMasterId: string | null;
  applyTo?: SeriesScope;
}): string {
  if (input.applyTo === 'entireSeries') {
    assert.ok(
      input.seriesMasterId !== null && input.seriesMasterId.length > 0,
      'seriesMasterId must already be set for entireSeries',
    );
    return input.seriesMasterId;
  }
  return input.eventId;
}
