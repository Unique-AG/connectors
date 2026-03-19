import { assert } from 'vitest';

type NonEmptyArray<T> = [T, ...T[]];
type Callback<T> = () => Promise<{ status: 'continue' | 'stop'; result: T }>;

export const pipeline = async <T>(args: NonEmptyArray<Callback<T>>): Promise<T> => {
  let i = 0;
  for (const item of args) {
    const { status, result } = await item();
    if (status === 'stop') {
      return result;
    }
    i++;
    if (i === args.length) {
      return result;
    }
  }
  assert.fail(`Empty args`);
};
