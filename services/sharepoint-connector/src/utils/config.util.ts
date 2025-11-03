import { z } from 'zod';

export const parseJsonEnvironmentVariable = (fieldName: string) =>
  z
    .string()
    .transform((val) => {
      if (!val) return {};
      try {
        return JSON.parse(val);
      } catch (error) {
        throw new Error(
          `Invalid JSON for ${fieldName}: ${error instanceof Error ? error.message : 'Unknown error'}`,
        );
      }
    })
    .catch(() => ({}));
