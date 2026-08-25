import { MCP_TOOL_METADATA_KEY, type ToolOptions } from '@unique-ag/mcp-server-module';
import { describe, expect, it } from 'vitest';
import * as z from 'zod';
import { CALENDAR_TOOLS } from '../../backend.module';

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

/**
 * Reads the @Tool metadata straight off the registered classes, so a tool added to
 * registerBackendModule is covered here without anyone remembering to update a list.
 */
function registeredTools(): { name: string; options: ToolOptions }[] {
  return CALENDAR_TOOLS.map((toolClass) => {
    const prototype = toolClass.prototype as unknown as Record<string, unknown>;
    const handler = Object.getOwnPropertyNames(prototype)
      .filter((key) => key !== 'constructor')
      .map((key) => prototype[key])
      .find(
        (value) =>
          typeof value === 'function' &&
          Reflect.getMetadata(MCP_TOOL_METADATA_KEY, value) !== undefined,
      );
    expect(handler, `${toolClass.name} has no @Tool method`).toBeDefined();
    const options = Reflect.getMetadata(MCP_TOOL_METADATA_KEY, handler as object) as ToolOptions;
    return { name: options.name ?? toolClass.name, options };
  });
}

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
  it.each(registeredTools())('$name has _meta and a description on every input and output field', ({
    name,
    options,
  }) => {
    const meta = options._meta as Record<string, string> | undefined;
    expect(meta?.['unique.app/icon'], `${name} icon`).toBe('calendar');
    expect(meta?.['unique.app/system-prompt']?.length ?? 0).toBeGreaterThan(0);
    expect(meta?.['unique.app/tool-format-information']?.length ?? 0).toBeGreaterThan(0);
    expect(options.description?.length ?? 0).toBeGreaterThan(0);
    expect(options.outputSchema, `${name} outputSchema`).toBeDefined();

    const input = z.toJSONSchema(options.parameters, { io: 'input' }) as JsonSchema;
    const output = z.toJSONSchema(
      options.outputSchema as NonNullable<typeof options.outputSchema>,
      { io: 'output' },
    ) as JsonSchema;

    expect(missingFieldDescriptions(input, 'input', input.$defs ?? {})).toEqual([]);
    expect(missingFieldDescriptions(output, 'output', output.$defs ?? {})).toEqual([]);
  });

  it('covers every registered calendar tool', () => {
    expect(
      registeredTools()
        .map((tool) => tool.name)
        .sort(),
    ).toEqual([
      'cancel_event',
      'check_availability',
      'create_event',
      'list_calendars',
      'respond_to_invite',
      'search_calendar_events',
      'suggest_meeting_times',
      'update_event',
    ]);
  });
});
