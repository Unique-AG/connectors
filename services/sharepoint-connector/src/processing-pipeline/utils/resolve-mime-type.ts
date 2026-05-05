import { entries, find, map, pipe, sortBy } from 'remeda';
import { DEFAULT_MIME_TYPE } from '../../constants/defaults.constants';

// Map keys are lowercased defensively so the helper is safe to use independently of the schema's
// normalization. Sorting per call is fine: maps are small and the cost is negligible relative to
// per-file processing.
export function resolveMimeType(
  fileName: string,
  rawMimeType: string | undefined,
  overrides: Record<string, string>,
): string {
  const lowerFileName = fileName.toLowerCase();
  const match = pipe(
    overrides,
    entries(),
    map(([suffix, mimeType]) => [suffix.toLowerCase(), mimeType] as const),
    sortBy(([suffix]) => -suffix.length),
    find(([suffix]) => lowerFileName.endsWith(suffix)),
  );

  return match ? match[1] : (rawMimeType ?? DEFAULT_MIME_TYPE);
}
