import { describe, expect, it } from 'vitest';
import { findBestMatch } from './find-best-match';

interface Item {
  id: string;
  label: string;
}

const items: Item[] = [
  { id: 'inbox', label: 'Inbox' },
  { id: 'sent', label: 'Sent Items' },
];

const getLabel = (item: Item) => item.label;

describe('findBestMatch', () => {
  it('returns the item with exact label match', () => {
    const result = findBestMatch(items, getLabel, 'Inbox', 0.8);

    expect(result).toEqual({ id: 'inbox', label: 'Inbox' });
  });

  it('returns the item when similarity is at the threshold', () => {
    // "Inboc" vs "Inbox": distance 1, max length 5 → similarity 0.8
    const result = findBestMatch(items, getLabel, 'Inboc', 0.8);

    expect(result).toEqual({ id: 'inbox', label: 'Inbox' });
  });

  it('returns undefined when best similarity is below the threshold', () => {
    // "Inbcc" vs "Inbox": distance 2, max length 5 → similarity 0.6
    const result = findBestMatch(items, getLabel, 'Inbcc', 0.8);

    expect(result).toBeUndefined();
  });

  it('returns undefined when items list is empty', () => {
    const result = findBestMatch([], getLabel, 'Inbox', 0.8);

    expect(result).toBeUndefined();
  });

  it('matches both empty query and label as identical', () => {
    const emptyItems: Item[] = [{ id: 'empty', label: '' }];

    const result = findBestMatch(emptyItems, getLabel, '', 1.0);

    expect(result).toEqual({ id: 'empty', label: '' });
  });
});
