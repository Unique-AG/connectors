import * as z from 'zod';
import { RELATIVE_RANGE_DESCRIPTIONS, RELATIVE_RANGES } from './relative-range';

const relativeRangeLiterals = RELATIVE_RANGES.map((range) =>
  z.literal(range).describe(RELATIVE_RANGE_DESCRIPTIONS[range]),
);

export const RelativeRangeSchema = z.union(
  relativeRangeLiterals as [
    (typeof relativeRangeLiterals)[number],
    (typeof relativeRangeLiterals)[number],
    ...(typeof relativeRangeLiterals)[number][],
  ],
);
