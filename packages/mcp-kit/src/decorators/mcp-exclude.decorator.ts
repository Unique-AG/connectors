import { MCP_EXCLUDED_PARAMS } from '../constants';
import { invariant } from '../errors/defect.js';

export interface ExcludedParamEntry {
  index: number;
  reason: 'inject' | 'inject-repository' | 'mcp-exclude' | 'custom-di';
}

export function McpExclude(): ParameterDecorator {
  return (target, propertyKey, parameterIndex) => {
    invariant(propertyKey !== undefined, '@McpExclude() must be applied to a method parameter, not a constructor parameter');
    const existing: ExcludedParamEntry[] =
      (Reflect.getMetadata(MCP_EXCLUDED_PARAMS, target, propertyKey) as ExcludedParamEntry[] | undefined) ?? [];
    Reflect.defineMetadata(
      MCP_EXCLUDED_PARAMS,
      [...existing, { index: parameterIndex, reason: 'mcp-exclude' }],
      target,
      propertyKey,
    );
  };
}
