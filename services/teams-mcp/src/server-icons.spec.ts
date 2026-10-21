import { describe, expect, it } from 'vitest';
import { serverIcons } from './server-icons';

describe('serverIcons', () => {
  it('advertises one inline png within the hub size cap', () => {
    const [icon] = serverIcons;

    expect(serverIcons).toHaveLength(1);
    expect(icon?.src).toMatch(/^data:image\/png;base64,/);
    expect(icon?.src.length).toBeLessThanOrEqual(100 * 1024);
  });

  it('encodes a real png', () => {
    const base64 = serverIcons[0]?.src.split(',')[1] ?? '';

    expect(Buffer.from(base64, 'base64').subarray(1, 4).toString()).toBe('PNG');
  });
});
