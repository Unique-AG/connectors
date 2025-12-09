import { z } from 'zod';

export const parseJsonEnvironmentVariable = (fieldName: string) =>
  z.string().transform((val) => {
    if (!val) return {};
    try {
      return JSON.parse(val);
    } catch (error) {
      throw new Error(
        `Invalid JSON for ${fieldName}: ${error instanceof Error ? error.message : 'Unknown error'}`,
      );
    }
  });

export const parseCommaSeparatedArray = (value: unknown): string[] => {
  if (Array.isArray(value)) {
    return value;
  }

  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed
      ? trimmed
          .split(',')
          .map((item) => item.trim())
          .filter(Boolean)
      : [];
  }

  return [];
};
