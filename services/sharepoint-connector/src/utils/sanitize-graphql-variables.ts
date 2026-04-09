import { shouldDiscloseLogs, smear } from './logging.util';

/**
 * Flat list of dot-separated paths pointing to **leaf** fields within GraphQL
 * variables that are safe to log as-is.
 *
 * Only concrete leaf paths are accepted — whitelisting an intermediate object
 * key (e.g. `'input'`) does **not** implicitly whitelist its children. This is
 * intentional: every loggable field must be explicitly opted-in so that newly
 * added nested fields default to being smeared.
 */
export type VariableLogPolicy = readonly string[];

/**
 * Sanitises GraphQL variables for logging by smearing every string leaf that
 * is not explicitly listed in `logSafeKeys`.
 *
 * Designed for the plain-JSON value types that appear in GraphQL variables:
 * strings, numbers, booleans, nulls, plain objects and arrays.
 * It does **not** handle class instances, Dates, Maps, Sets, or other
 * non-JSON types — those are never present in GraphQL variable payloads.
 */
export function sanitizeGraphqlVariables(
  variables: Record<string, unknown> | undefined,
  logSafeKeys: VariableLogPolicy | undefined,
): Record<string, unknown> | undefined {
  if (!variables) {
    return variables;
  }

  if (shouldDiscloseLogs()) {
    return variables;
  }

  const safeSet = new Set(logSafeKeys);
  return walkAndSmear(variables, '', safeSet) as Record<string, unknown>;
}

function walkAndSmear(value: unknown, currentPath: string, safeKeys: Set<string>): unknown {
  if (value === null || value === undefined) {
    return value;
  }

  if (Array.isArray(value)) {
    return value.map((item) => walkAndSmear(item, currentPath, safeKeys));
  }

  if (typeof value === 'object') {
    const result: Record<string, unknown> = {};
    for (const [key, val] of Object.entries(value)) {
      const childPath = currentPath ? `${currentPath}.${key}` : key;
      result[key] = walkAndSmear(val, childPath, safeKeys);
    }
    return result;
  }

  if (safeKeys.has(currentPath)) {
    return value;
  }

  if (typeof value === 'string') {
    return smear(value);
  }

  if (typeof value === 'number' || typeof value === 'boolean') {
    return value;
  }

  return '[Smeared]';
}
