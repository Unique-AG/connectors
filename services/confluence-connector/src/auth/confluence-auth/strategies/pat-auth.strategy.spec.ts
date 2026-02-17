import { describe, expect, it } from 'vitest';
import { AuthMode } from '../../../config/confluence.schema';
import { Redacted } from '../../../utils/redacted';
import { PatAuthStrategy } from './pat-auth.strategy';

describe('PatAuthStrategy', () => {
  const authConfig = {
    mode: AuthMode.PAT,
    token: new Redacted('my-personal-access-token'),
  };

  it('returns the unwrapped token value as accessToken', async () => {
    const strategy = new PatAuthStrategy(authConfig);

    const result = await strategy.acquireToken();

    expect(result).toBe('my-personal-access-token');
  });

  it('returns the same token on multiple calls', async () => {
    const strategy = new PatAuthStrategy(authConfig);

    const first = await strategy.acquireToken();
    const second = await strategy.acquireToken();

    expect(first).toBe(second);
    expect(first).toBe('my-personal-access-token');
  });
});
