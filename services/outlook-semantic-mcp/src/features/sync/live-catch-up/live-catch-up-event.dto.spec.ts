import { describe, expect, it } from 'vitest';
import { LiveCatchUpExecutEventDto, LiveCatchUpReadyRecheckEventDto } from './live-catch-up-event.dto';

describe('LiveCatchUpExecutEventDto', () => {
  const type = 'unique.outlook-semantic-mcp.live-catch-up.execute';

  it('accepts payload with only subscriptionId', () => {
    const result = LiveCatchUpExecutEventDto.safeParse({
      type,
      payload: { subscriptionId: 'sub-123' },
    });
    expect(result.success).toBe(true);
  });

  it('accepts payload with only userProfileId', () => {
    const result = LiveCatchUpExecutEventDto.safeParse({
      type,
      payload: { userProfileId: 'user-456' },
    });
    expect(result.success).toBe(true);
  });

  it('accepts payload with both subscriptionId and userProfileId', () => {
    const result = LiveCatchUpExecutEventDto.safeParse({
      type,
      payload: { subscriptionId: 'sub-123', userProfileId: 'user-456' },
    });
    expect(result.success).toBe(true);
  });

  it('rejects payload with neither field', () => {
    const result = LiveCatchUpExecutEventDto.safeParse({
      type,
      payload: {},
    });
    expect(result.success).toBe(false);
  });
});

describe('LiveCatchUpReadyRecheckEventDto', () => {
  const type = 'unique.outlook-semantic-mcp.live-catch-up.ready-recheck';

  it('accepts payload with only subscriptionId', () => {
    const result = LiveCatchUpReadyRecheckEventDto.safeParse({
      type,
      payload: { subscriptionId: 'sub-123' },
    });
    expect(result.success).toBe(true);
  });

  it('accepts payload with only userProfileId', () => {
    const result = LiveCatchUpReadyRecheckEventDto.safeParse({
      type,
      payload: { userProfileId: 'user-456' },
    });
    expect(result.success).toBe(true);
  });

  it('accepts payload with both subscriptionId and userProfileId', () => {
    const result = LiveCatchUpReadyRecheckEventDto.safeParse({
      type,
      payload: { subscriptionId: 'sub-123', userProfileId: 'user-456' },
    });
    expect(result.success).toBe(true);
  });

  it('rejects payload with neither field', () => {
    const result = LiveCatchUpReadyRecheckEventDto.safeParse({
      type,
      payload: {},
    });
    expect(result.success).toBe(false);
  });
});
