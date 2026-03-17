import { distance } from 'fastest-levenshtein';
import { isNullish } from 'remeda';

export function findBestMatch<T>({
  items,
  getLabel,
  query,
  threshold,
  isNewItemBetter,
}: {
  items: T[];
  getLabel: (item: T) => string;
  query: string;
  threshold: number;
  isNewItemBetter?: (newItem: T, currentBestSimilarity: T) => boolean;
}): T | undefined {
  const lowerQuery = query.toLowerCase();
  let bestSimilarity = 0;
  let bestItem: T | undefined;

  for (const item of items) {
    const lowerLabel = getLabel(item).toLowerCase();
    const dist = distance(lowerQuery, lowerLabel);
    const maxLen = Math.max(lowerQuery.length, lowerLabel.length);
    const similarity = maxLen === 0 ? 1 : 1 - dist / maxLen;
    if (similarity > bestSimilarity || isNullish(bestItem)) {
      bestSimilarity = similarity;
      bestItem = item;
    } else if (bestItem && similarity === bestSimilarity && isNewItemBetter?.(item, bestItem)) {
      bestItem = item;
    }
  }

  return bestSimilarity >= threshold ? bestItem : undefined;
}
