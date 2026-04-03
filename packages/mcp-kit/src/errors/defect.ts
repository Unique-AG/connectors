/**
 * Represents an unrecoverable programming mistake (defect), as opposed to an
 * operational failure. Thrown when code reaches a state that should be impossible
 * under correct usage — e.g. a missing required dependency or broken invariant.
 *
 * The `_tag` discriminant (`'Defect'`) distinguishes defects from `McpBaseError`
 * operational failures so error boundaries can handle them differently.
 */
export class DefectError extends Error {
  public readonly _tag = 'Defect' as const;
  public override readonly name = 'DefectError';
}

/**
 * Asserts that `condition` is truthy, throwing a plain `Error` with `message` if not.
 * Use this to guard against states that indicate a programming error rather than
 * expected runtime failures.
 *
 * @throws {Error} When `condition` is falsy.
 */
export function invariant(condition: unknown, message: string): asserts condition {
  if (!condition) {
    throw new Error(message);
  }
}
