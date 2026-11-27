import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { TOOL_NAMES } from '../tool-declarations';

const CHART_DIR = join(__dirname, '../../../deploy/helm-charts/outlook-semantic-mcp');

const toolNamesIn = (schemaFile: string): unknown =>
  JSON.parse(readFileSync(join(CHART_DIR, schemaFile), 'utf8')).properties.mcpConfig.properties.app
    .properties.tools.items.enum;

describe('the chart schema', () => {
  it.each(['values.additional.schema.json', 'values.schema.json'])(
    'accepts exactly the tools the server knows in %s',
    (schemaFile) => {
      expect(toolNamesIn(schemaFile)).toEqual(TOOL_NAMES);
    },
  );
});
