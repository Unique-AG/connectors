import { describe, expect, it } from 'vitest';
import { GRAPH_ID_PATTERN } from '../graph-id-pattern';

describe('GRAPH_ID_PATTERN', () => {
  it.each(['draft-1', 'AAMkAGI2THVSAAA=', 'AQMk/ADRh+immutable_id=', 'AAk-Zm9v_YmFy'])(
    'accepts the Graph id %s',
    (id) => {
      expect(GRAPH_ID_PATTERN.test(id)).toBe(true);
    },
  );

  it.each([
    ['empty', ''],
    ['a query string', 'abc?$select=body'],
    ['a fragment', 'abc#frag'],
    ['a percent escape', 'abc%2e%2e'],
    ['a second query parameter', 'abc&x=1'],
    ['a space', 'abc def'],
    ['a newline', 'abc\ndef'],
    ['a path made of dots', '../me'],
    ['a colon', 'abc:def'],
  ])('rejects %s', (_name, id) => {
    expect(GRAPH_ID_PATTERN.test(id)).toBe(false);
  });
});
