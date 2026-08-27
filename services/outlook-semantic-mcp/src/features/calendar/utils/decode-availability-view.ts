import { Temporal } from 'temporal-polyfill';
import { toGraphInstant } from '~/utils/relative-range';

export const BUSY_STATUSES = ['tentative', 'busy', 'oof', 'workingElsewhere', 'unknown'] as const;

export type BusyStatus = (typeof BUSY_STATUSES)[number];

export interface AvailabilityBlock {
  status: BusyStatus;
  startDateTime: string;
  endDateTime: string;
}

const STATUS_BY_CODE: Record<string, BusyStatus | 'free'> = {
  '0': 'free',
  '1': 'tentative',
  '2': 'busy',
  '3': 'oof',
  '4': 'workingElsewhere',
};

export function decodeAvailabilityView(input: {
  availabilityView: string;
  start: Temporal.ZonedDateTime;
  intervalMinutes: number;
}): AvailabilityBlock[] {
  const blocks: AvailabilityBlock[] = [];
  let index = 0;
  while (index < input.availabilityView.length) {
    const code = input.availabilityView[index];
    let end = index + 1;
    while (end < input.availabilityView.length && input.availabilityView[end] === code) {
      end += 1;
    }
    const status = STATUS_BY_CODE[code ?? ''] ?? 'unknown';
    if (status !== 'free') {
      blocks.push({
        status,
        startDateTime: toGraphInstant(input.start.add({ minutes: input.intervalMinutes * index })),
        endDateTime: toGraphInstant(input.start.add({ minutes: input.intervalMinutes * end })),
      });
    }
    index = end;
  }
  return blocks;
}
