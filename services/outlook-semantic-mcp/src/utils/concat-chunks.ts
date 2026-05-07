import { join, map, pipe, sortBy } from 'remeda';
import { stripChunkTags } from './strip-chunk-tags';

export const concatChunks = (chunks: { order: number | null; text: string }[]): string => {
  return pipe(
    chunks,
    sortBy((item) => item.order ?? Number.MAX_SAFE_INTEGER),
    // We keep the chunk tags on the first chunk but remove them from others.
    map((item, index) => (index === 0 ? item.text : stripChunkTags(item.text))),
    join('\n'),
  );
};
