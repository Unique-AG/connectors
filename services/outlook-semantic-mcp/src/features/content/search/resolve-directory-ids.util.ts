import { systemDirectories } from '~/db';
import { findBestMatch } from '~/utils/find-best-match';

export function resolveDirectoryIds(
  rawIds: string[],
  availableDirectories: Array<{
    providerDirectoryId: string;
    displayName: string;
    internalType: string;
  }>,
): { resolvedIds: string[]; unrecognized: string[] } {
  const resolvedIds: string[] = [];
  const unrecognized: string[] = [];

  for (const rawId of rawIds) {
    if (!rawId.trim().length) {
      continue;
    }
    const exactMatch = availableDirectories.find(
      ({ providerDirectoryId }) => providerDirectoryId === rawId,
    );
    if (exactMatch) {
      resolvedIds.push(rawId);
      continue;
    }

    const bestDirectory = findBestMatch({
      items: availableDirectories,
      getLabel: (directory) => directory.displayName,
      query: rawId,
      threshold: 0.8,
      isNewItemBetter: (newItem, currentBestItem) => {
        if (systemDirectories.includes(currentBestItem.internalType)) {
          return false;
        }
        return systemDirectories.includes(newItem.internalType);
      },
    });
    if (bestDirectory) {
      resolvedIds.push(bestDirectory.providerDirectoryId);
    } else {
      unrecognized.push(rawId);
    }
  }

  return { resolvedIds, unrecognized };
}
