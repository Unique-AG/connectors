function databaseError(error: unknown): unknown {
  return error instanceof Error && error.cause !== undefined ? error.cause : error;
}

export function isUniqueViolation(error: unknown, constraint: string): boolean {
  const cause = databaseError(error);
  return (
    typeof cause === 'object' &&
    cause !== null &&
    Reflect.get(cause, 'code') === '23505' &&
    Reflect.get(cause, 'constraint') === constraint
  );
}

export function isForeignKeyViolation(error: unknown): boolean {
  const cause = databaseError(error);
  return typeof cause === 'object' && cause !== null && Reflect.get(cause, 'code') === '23503';
}
