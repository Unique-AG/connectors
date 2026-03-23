export class DefectError extends Error {
  public readonly _tag = 'Defect' as const;
  public override readonly name = 'DefectError';
}

export function invariant(condition: unknown, message: string): asserts condition {
  if (!condition) {
    throw new Error(message);
  }
}
