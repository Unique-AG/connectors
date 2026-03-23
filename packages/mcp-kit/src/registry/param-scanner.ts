import { MCP_CTX_PARAM_INDEX, MCP_EXCLUDED_PARAMS } from '../constants';
import type { ExcludedParamEntry } from '../decorators/mcp-exclude.decorator';

const SELF_DECLARED_DEPS_METADATA = 'self:properties_metadata';
const PARAMTYPES_METADATA = 'design:paramtypes';

export interface ParamScanResult {
  ctxParamIndex: number | undefined;
  excludedParams: ExcludedParamEntry[];
}

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
    Reflect.getMetadata(MCP_EXCLUDED_PARAMS, target, methodName) ?? [];

  const selfDeclaredDeps: Array<{ index: number; param: unknown }> =
    Reflect.getMetadata(SELF_DECLARED_DEPS_METADATA, (target as { constructor: unknown }).constructor) ?? [];

  const paramTypes: unknown[] =
    Reflect.getMetadata(PARAMTYPES_METADATA, target, methodName) ?? [];

  const injectExcluded: ExcludedParamEntry[] = selfDeclaredDeps
    .filter(
      (dep) =>
        dep.index < paramTypes.length &&
        !mcpExcludedParams.some((e) => e.index === dep.index),
    )
    .map((dep) => ({ index: dep.index, reason: 'inject' as const }));

  const allExcluded = [...mcpExcludedParams, ...injectExcluded];

  return {
    ctxParamIndex,
    excludedParams: allExcluded,
  };
}

export function getMcpInputParamIndices(
  paramCount: number,
  ctxParamIndex: number | undefined,
  excludedParams: ExcludedParamEntry[],
): number[] {
  const excluded = new Set<number>(excludedParams.map((e) => e.index));
  if (ctxParamIndex !== undefined) {
    excluded.add(ctxParamIndex);
  }
  return Array.from({ length: paramCount }, (_, i) => i).filter(
    (i) => !excluded.has(i),
  );
}
