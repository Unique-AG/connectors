import { describe, expect, it } from 'vitest';
import * as z from 'zod';
import { ListCalendarsInputSchema, ListCalendarsOutputSchema } from '../list-calendars.tool';
import { META as LIST_CALENDARS_META } from '../list-calendars-tool.meta';
import {
  SearchCalendarEventsInputSchema,
  SearchCalendarEventsOutputSchema,
} from '../search-calendar-events.tool';
import { META as SEARCH_CALENDAR_EVENTS_META } from '../search-calendar-events-tool.meta';

interface JsonSchema {
  description?: string;
  properties?: Record<string, JsonSchema>;
  items?: JsonSchema | JsonSchema[];
  anyOf?: JsonSchema[];
  oneOf?: JsonSchema[];
  allOf?: JsonSchema[];
  $defs?: Record<string, JsonSchema>;
  $ref?: string;
}

const CALENDAR_TOOLS = [
  {
    name: 'list_calendars',
    meta: LIST_CALENDARS_META,
    input: ListCalendarsInputSchema,
    output: ListCalendarsOutputSchema,
  },
  {
    name: 'search_calendar_events',
    meta: SEARCH_CALENDAR_EVENTS_META,
    input: SearchCalendarEventsInputSchema,
    output: SearchCalendarEventsOutputSchema,
  },
] as const;

function resolveRef(schema: JsonSchema, defs: Record<string, JsonSchema>): JsonSchema {
  if (schema.$ref === undefined) {
    return schema;
  }
  const name = schema.$ref.replace('#/$defs/', '');
  const resolved = defs[name];
  return resolved === undefined
    ? schema
    : { ...resolved, description: schema.description ?? resolved.description };
}

function missingFieldDescriptions(
  schema: JsonSchema,
  path: string,
  defs: Record<string, JsonSchema>,
): string[] {
  const resolved = resolveRef(schema, defs);
  const nextDefs = resolved.$defs ?? defs;
  const missing: string[] = [];
  if (resolved.properties !== undefined) {
    for (const [key, value] of Object.entries(resolved.properties)) {
      const childPath = path === '' ? key : `${path}.${key}`;
      const child = resolveRef(value, nextDefs);
      if (child.description === undefined || child.description.trim() === '') {
        missing.push(childPath);
      }
      missing.push(...missingFieldDescriptions(value, childPath, nextDefs));
    }
  }
  const nested = [
    ...(resolved.anyOf ?? []),
    ...(resolved.oneOf ?? []),
    ...(resolved.allOf ?? []),
    ...(Array.isArray(resolved.items)
      ? resolved.items
      : resolved.items === undefined
        ? []
        : [resolved.items]),
  ];
  for (const child of nested) {
    missing.push(...missingFieldDescriptions(child, path, nextDefs));
  }
  return missing;
}

describe('calendar tool schema harmony', () => {
  it.each(
    CALENDAR_TOOLS,
  )('$name has _meta and a description on every input and output field', (tool) => {
    expect(tool.meta['unique.app/icon']).toBe('calendar');
    expect(tool.meta['unique.app/system-prompt']?.length).toBeGreaterThan(0);
    expect(tool.meta['unique.app/tool-format-information']?.length).toBeGreaterThan(0);

    const input = z.toJSONSchema(tool.input, { io: 'input' }) as JsonSchema;
    const output = z.toJSONSchema(tool.output, { io: 'output' }) as JsonSchema;

    expect(missingFieldDescriptions(input, 'input', input.$defs ?? {})).toEqual([]);
    expect(missingFieldDescriptions(output, 'output', output.$defs ?? {})).toEqual([]);
  });
});
