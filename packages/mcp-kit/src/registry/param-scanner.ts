import { filter, map, pipe, range } from 'remeda';
import { MCP_CTX_PARAM_INDEX, MCP_EXCLUDED_PARAMS } from '../constants';
import type { ExcludedParamEntry } from '../decorators/mcp-exclude.decorator';

/** NestJS reflect-metadata key for constructor parameters declared via `@Inject()`. */
const SELF_DECLARED_DEPS_METADATA = 'self:properties_metadata';
/** TypeScript emit key that stores the design-time parameter types of a method. */
const PARAMTYPES_METADATA = 'design:paramtypes';

/** Result of scanning a method's parameter decorators for MCP-relevant metadata. */
export interface ParamScanResult {
  /** Index of the parameter decorated with `@McpCtx()`, or `undefined` if not present. */
  ctxParamIndex: number | undefined;
  /** Parameters that should not be treated as MCP tool input (ctx param + NestJS-injected params). */
  excludedParams: ExcludedParamEntry[];
}

/**
 * Scans a method's reflect-metadata to find the `@McpCtx()` parameter index and all parameters
 * that should be excluded from MCP tool input — both explicitly excluded ones (`@McpExclude()`)
 * and parameters injected by NestJS via `@Inject()`.
 */
export function scanMethodParams(
  target: object,
  methodName: string,
): ParamScanResult {
  const ctxParamIndex: number | undefined = Reflect.getMetadata(
    MCP_CTX_PARAM_INDEX,
    target,
    methodName,
  );

  const mcpExcludedParams: ExcludedParamEntry[] =
    (Reflect.getMetadata(MCP_EXCLUDED_PARAMS, target, methodName) as ExcludedParamEntry[] | undefined) ?? [];

  const selfDeclaredDeps: Array<{ index: number; param: unknown }> =
    (Reflect.getMetadata(SELF_DECLARED_DEPS_METADATA, (target as { constructor: unknown }).constructor) as Array<{ index: number; param: unknown }> | undefined) ?? [];

  const paramTypes: unknown[] =
    (Reflect.getMetadata(PARAMTYPES_METADATA, target, methodName) as unknown[] | undefined) ?? [];

  const injectExcluded: ExcludedParamEntry[] = pipe(
    selfDeclaredDeps,
    filter((dep) => dep.index < paramTypes.length && !mcpExcludedParams.some((e) => e.index === dep.index)),
    map((dep) => ({ index: dep.index, reason: 'inject' as const })),
  );

  const allExcluded = [...mcpExcludedParams, ...injectExcluded];

  return {
    ctxParamIndex,
    excludedParams: allExcluded,
  };
}

/**
 * Returns the parameter indices that carry actual MCP tool input — i.e. every index in
 * `[0, paramCount)` that is neither the ctx param nor an excluded (NestJS-injected) param.
 */
export function getMcpInputParamIndices(
  paramCount: number,
  ctxParamIndex: number | undefined,
  excludedParams: ExcludedParamEntry[],
): number[] {
  const excludedIndices = new Set([
    ...map(excludedParams, (e) => e.index),
    ...(ctxParamIndex !== undefined ? [ctxParamIndex] : []),
  ]);
  return filter(range(0, paramCount), (i) => !excludedIndices.has(i));
}
