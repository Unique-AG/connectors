import { MCP_EXCLUDED_PARAMS } from '../constants';

export interface ExcludedParamEntry {
  index: number;
  reason: 'inject' | 'inject-repository' | 'mcp-exclude' | 'custom-di';
}

export function McpExclude(): ParameterDecorator {
  return (target, propertyKey, parameterIndex) => {
    const existing: ExcludedParamEntry[] =
      Reflect.getMetadata(MCP_EXCLUDED_PARAMS, target, propertyKey!) ?? [];
    Reflect.defineMetadata(
      MCP_EXCLUDED_PARAMS,
      [...existing, { index: parameterIndex, reason: 'mcp-exclude' }],
      target,
      propertyKey!,
    );
  };
}
