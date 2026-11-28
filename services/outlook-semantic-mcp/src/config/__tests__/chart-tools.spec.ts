import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { TOOL_NAMES, type ToolGroup, toolsInGroup } from '../tool-declarations';

const CHART_DIR = join(__dirname, '../../../deploy/helm-charts/outlook-semantic-mcp');

const toolNamesIn = (schemaFile: string): unknown =>
  JSON.parse(readFileSync(join(CHART_DIR, schemaFile), 'utf8')).properties.mcpConfig.properties.app
    .properties.tools.items.enum;

const toolsListedInTemplate = (variable: string): string[] => {
  const template = readFileSync(join(CHART_DIR, 'templates/_config-app.tpl'), 'utf8');
  const line = template.split('\n').find((text) => text.includes(`$${variable} := list `)) ?? '';
  return [...line.matchAll(/"([^"]+)"/g)].map((match) => match[1] ?? '');
};

describe('the chart schema', () => {
  it.each(['values.additional.schema.json', 'values.schema.json'])(
    'accepts exactly the tools the server knows in %s',
    (schemaFile) => {
      expect(toolNamesIn(schemaFile)).toEqual(TOOL_NAMES);
    },
  );
});

describe('the chart template', () => {
  it.each<[string, ToolGroup]>([
    ['syncTools', 'sync'],
    ['debugTools', 'debug'],
  ])('lists in $%s exactly the server’s %s tools', (variable, group) => {
    expect(toolsListedInTemplate(variable)).toEqual(toolsInGroup(group));
  });
});
