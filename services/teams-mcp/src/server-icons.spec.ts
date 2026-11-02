import { describe, expect, it } from 'vitest';
import { serverIcons } from './server-icons';

describe('serverIcons', () => {
  it('advertises one inline png within the hub size cap', () => {
    const [icon] = serverIcons;

    expect(serverIcons).toHaveLength(1);
    expect(icon?.src).toMatch(/^data:image\/png;base64,/);
    expect(icon?.src.length).toBeLessThanOrEqual(100 * 1024);
  });
});
