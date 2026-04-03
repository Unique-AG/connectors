import { MCP_EXCLUDED_PARAMS } from '../constants';
import { invariant } from '../errors/defect.js';

/** Recorded entry for a single parameter that must be excluded from MCP input mapping. */
export interface ExcludedParamEntry {
  /** Zero-based index of the parameter in the method signature. */
  index: number;
  /**
   * Why the parameter is excluded:
   * - `'inject'` — injected by the DI container (e.g. a service decorated with `@Inject`).
   * - `'inject-repository'` — injected repository (e.g. decorated with `@InjectRepository`).
   * - `'mcp-exclude'` — explicitly opted out via `@McpExclude()`.
   * - `'custom-di'` — excluded by a custom DI integration not covered by the above.
   */
  reason: 'inject' | 'inject-repository' | 'mcp-exclude' | 'custom-di';
}

/**
 * Parameter decorator that tells the MCP runtime to skip this parameter when building the
 * tool/resource/prompt input from the incoming MCP request.
 * Use it on parameters that are satisfied by the DI container (services, repositories, etc.)
 * and must not appear in the MCP input schema or be read from the caller's arguments.
 * Appends an {@link ExcludedParamEntry} with `reason: 'mcp-exclude'` to the
 * `MCP_EXCLUDED_PARAMS` metadata list on the method.
 */
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
