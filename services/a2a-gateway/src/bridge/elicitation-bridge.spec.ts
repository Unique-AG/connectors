import type { Part } from '@a2a-js/sdk';
import { describe, expect, it } from 'vitest';
import { answerParts, elicitationRequest } from './elicitation-bridge.js';

function text(value: string): Part {
  return { content: { $case: 'text', value }, metadata: undefined, filename: '', mediaType: '' };
}

function data(value: unknown): Part {
  return { content: { $case: 'data', value }, metadata: undefined, filename: '', mediaType: '' };
}

describe('elicitation bridge', () => {
  it('keeps a flat primitive form schema from the remote agent', () => {
    const request = elicitationRequest([
      text('Which city?'),
      data({
        type: 'object',
        properties: { city: { type: 'string', title: 'City', format: 'uri', default: 'x' } },
        required: ['city', 'unknown'],
      }),
    ]);
    expect(request).toEqual({
      message: 'Which city?',
      schema: {
        type: 'object',
        properties: { city: { type: 'string', title: 'City' } },
        required: ['city'],
      },
      freeText: false,
    });
  });

  it.each([
    ['nested objects', { type: 'object', properties: { a: { type: 'object' } } }],
    ['arrays of objects', { type: 'object', properties: { a: { type: 'array' } } }],
    ['non-object schemas', { type: 'string' }],
  ])('falls back to a free-text answer for %s', (_case, schema) => {
    const request = elicitationRequest([text('Details?'), data(schema)]);
    expect(request.freeText).toBe(true);
    expect(request.schema).toEqual({
      type: 'object',
      properties: { answer: { type: 'string', title: 'Answer' } },
      required: ['answer'],
    });
  });

  it('bounds the remote question and never sends an empty prompt', () => {
    expect(elicitationRequest([text('x'.repeat(5_000))]).message).toHaveLength(2_000);
    expect(elicitationRequest([]).message).toMatch(/needs more information/);
  });

  it('answers free text as text and forms as structured data', () => {
    const freeText = elicitationRequest([text('Details?')]).schema;
    expect(answerParts({ answer: 'Zurich' }, freeText)).toMatchObject([
      { content: { $case: 'text', value: 'Zurich' } },
    ]);
    expect(
      answerParts({ city: 'Zurich' }, { type: 'object', properties: { city: {} } }),
    ).toMatchObject([{ content: { $case: 'data', value: { city: 'Zurich' } } }]);
  });
});
