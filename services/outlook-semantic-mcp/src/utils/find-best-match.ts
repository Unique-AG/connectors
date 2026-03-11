import { distance } from 'fastest-levenshtein';

export function findBestMatch<T>(
  items: T[],
  getLabel: (item: T) => string,
  query: string,
  threshold: number,
): T | undefined {
  const lowerQuery = query.toLowerCase();
  let bestSimilarity = 0;
  let bestItem: T | undefined;

  for (const item of items) {
    const lowerLabel = getLabel(item).toLowerCase();
    const dist = distance(lowerQuery, lowerLabel);
    const maxLen = Math.max(lowerQuery.length, lowerLabel.length);
    const similarity = maxLen === 0 ? 1 : 1 - dist / maxLen;
    if (similarity > bestSimilarity) {
      bestSimilarity = similarity;
      bestItem = item;
    }
  }

  return bestSimilarity >= threshold ? bestItem : undefined;
}
