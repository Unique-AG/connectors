export const safeStringify = (input: unknown): string => {
  try {
    return JSON.stringify(input);
  } catch {
    return input?.toString?.() ?? `No implementation for toString`;
  }
};
