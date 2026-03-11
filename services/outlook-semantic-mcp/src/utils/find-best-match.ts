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
    const similarity = 1 - dist / Math.max(lowerQuery.length, lowerLabel.length);
    if (similarity > bestSimilarity) {
      bestSimilarity = similarity;
      bestItem = item;
    }
  }

  return bestSimilarity >= threshold ? bestItem : undefined;
}
