// Jaro-Winkler similarity implemented locally because available npm packages either
// lacked TypeScript types or were ESM-only, which caused build issues with this project.
// Reference code: https://github.com/jordanthomas/jaro-winkler

/**
 * Computes the Jaro-Winkler similarity between two strings.
 * Returns a value in [0, 1] where 1 means identical and 0 means no similarity.
 *
 * The algorithm is designed for short strings such as person names. Compared to
 * edit-distance metrics (e.g. Levenshtein), it rewards a common prefix and is more
 * tolerant of transpositions — both common in real-world name data.
 */
export function jaroWinkler(first: string, second: string): number {
  if (first.length === 0 || second.length === 0) {
    return 0;
  }
  if (first === second) {
    return 1;
  }

  // Characters are considered matching only when they fall within this window.
  const matchWindow = Math.floor(Math.max(first.length, second.length) / 2) - 1;

  const firstMatched = new Array<boolean>(first.length).fill(false);
  const secondMatched = new Array<boolean>(second.length).fill(false);
  let matchCount = 0;

  // Step 1: find matching characters within the match window.
  for (let firstIndex = 0; firstIndex < first.length; firstIndex++) {
    const low = Math.max(0, firstIndex - matchWindow);
    const high = Math.min(firstIndex + matchWindow, second.length - 1);

    for (let secondIndex = low; secondIndex <= high; secondIndex++) {
      if (
        !firstMatched[firstIndex] &&
        !secondMatched[secondIndex] &&
        first[firstIndex] === second[secondIndex]
      ) {
        firstMatched[firstIndex] = secondMatched[secondIndex] = true;
        matchCount++;
        break;
      }
    }
  }

  if (matchCount === 0) {
    return 0;
  }

  // Step 2: count transpositions — matched characters that are out of order.
  let transpositions = 0;
  let secondCursor = 0;

  for (let firstIndex = 0; firstIndex < first.length; firstIndex++) {
    if (!firstMatched[firstIndex]) {
      continue;
    }
    while (!secondMatched[secondCursor]) {
      secondCursor++;
    }
    if (first[firstIndex] !== second[secondCursor]) {
      transpositions++;
    }
    secondCursor++;
  }

  // Step 3: compute base Jaro score.
  const jaro =
    (matchCount / first.length +
      matchCount / second.length +
      (matchCount - transpositions / 2) / matchCount) /
    3;

  // Step 4: apply Winkler prefix bonus (up to 4 characters, scaling factor 0.1).
  // Only applied when the Jaro score is already high (> 0.7) to avoid boosting
  // weak matches that happen to share a prefix.
  if (jaro <= 0.7) {
    return jaro;
  }

  let prefixLength = 0;
  while (prefixLength < 4 && first[prefixLength] === second[prefixLength]) {
    prefixLength++;
  }

  return jaro + prefixLength * 0.1 * (1 - jaro);
}
