import { expect } from 'vitest';
import type { UniqueState } from './unique-state';

export interface ExpectedContent {
  pages?: string[];
  attachments?: string[];
}

function toKeys(content: ExpectedContent): string[] {
  return [...(content.pages ?? []), ...(content.attachments ?? [])];
}

/**
 * Asserts every given page and attachment key reached Unique. Use it to state
 * what a sync should have ingested without caring about ordering or what else
 * is present.
 */
export function expectIngested(state: UniqueState, content: ExpectedContent): void {
  const present = new Set(state.files.map((file) => file.key));
  const missing = toKeys(content).filter((key) => !present.has(key));
  expect(missing).toEqual([]);
}

/**
 * Asserts none of the given page and attachment keys reached Unique. Use it for
 * content the sync should have filtered out or deleted.
 */
export function expectNotIngested(state: UniqueState, content: ExpectedContent): void {
  const present = new Set(state.files.map((file) => file.key));
  const unexpected = toKeys(content).filter((key) => present.has(key));
  expect(unexpected).toEqual([]);
}
