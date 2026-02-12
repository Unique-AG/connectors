import { SetMetadata } from '@nestjs/common';

export const UPTIME_CHECK_METADATA_KEY = 'up:check';

export function UptimeCheck(name?: string) {
  return SetMetadata(UPTIME_CHECK_METADATA_KEY, { name });
}
