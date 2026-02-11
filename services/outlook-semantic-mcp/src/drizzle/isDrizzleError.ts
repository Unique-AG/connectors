import { DrizzleQueryError } from "drizzle-orm";
import { DatabaseError } from "pg";

type DrizzleDatabaseError = DrizzleQueryError & { cause: DatabaseError };

export const isDrizzleDatabaseError = (
  error: unknown,
): error is DrizzleDatabaseError => {
  return (
    error instanceof DrizzleQueryError && error.cause instanceof DatabaseError
  );
};

export const isDrizzleDuplicateFieldError = (error: unknown): boolean => {
  return (
    isDrizzleDatabaseError(error) &&
    [
      // 'A duplicate entry was found for a unique field.'
      "23505",
    ].includes(error.cause.code ?? "")
  );
};
