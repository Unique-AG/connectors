import { setTimeout as sleep } from 'node:timers/promises';
import pinoHttp from 'pino-http';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  createSecretRedactor,
  runWithLogSecrets,
  type SecretRedactionOptions,
} from './redact-secrets';

const mockSecret = 'resilience-secret-0123';

// None of these characters occur in `[Redacted]`, so a secret built from them cannot reappear
// across the edge of a replacement and every leftover occurrence is a real leak.
const SECRET_ALPHABET = [
  '"',
  '\\',
  '\n',
  '\t',
  'é',
  '😀',
  '\ud800',
  '$',
  '&',
  '%',
  '+',
  '/',
  ' ',
  'x',
  'y',
  'z',
  '0',
  '7',
];
const TEXT_ALPHABET = [
  ...SECRET_ALPHABET,
  '{',
  '}',
  ':',
  ',',
  '[',
  ']',
  'Bearer ',
  'password=',
  '\u0000',
  '\u2028',
];

function createCapturingLogger(redaction: SecretRedactionOptions = {}) {
  const lines: string[] = [];
  const { logger } = pinoHttp({
    hooks: { streamWrite: createSecretRedactor(redaction) },
    stream: { write: (line: string) => lines.push(line) },
  });
  return { logger, lines };
}

// mulberry32: a seeded generator, so a failing run can be replayed.
function seededRandom(seed: number): () => number {
  let state = seed;
  return () => {
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function randomString(random: () => number, alphabet: readonly string[], length: number): string {
  return Array.from({ length }, () => alphabet[Math.floor(random() * alphabet.length)]).join('');
}

function stringValues(value: unknown): string[] {
  if (typeof value === 'string') {
    return [value];
  }
  if (Array.isArray(value)) {
    return value.flatMap(stringValues);
  }
  if (typeof value === 'object' && value !== null) {
    return Object.values(value).flatMap(stringValues);
  }
  return [];
}

describe('createSecretRedactor resilience', () => {
  describe('random records', () => {
    it.each([1, 2, 3, 4, 5])(
      'never throws, always writes valid JSON and never leaks (seed %i)',
      async (seed) => {
        const random = seededRandom(seed);
        const knownSecrets = Array.from({ length: 3 }, () =>
          randomString(random, SECRET_ALPHABET, 8 + Math.floor(random() * 8)),
        );
        const { logger, lines } = createCapturingLogger({ secrets: knownSecrets });
        const contextSecrets = Array.from({ length: 2 }, () =>
          randomString(random, SECRET_ALPHABET, 8 + Math.floor(random() * 8)),
        );
        const allSecrets = [...knownSecrets, ...contextSecrets];
        const withSecrets = () => {
          const text = randomString(random, TEXT_ALPHABET, Math.floor(random() * 20));
          const secret = allSecrets[Math.floor(random() * allSecrets.length)];
          return random() < 0.5 ? `${text}${secret}${text}` : text;
        };

        await runWithLogSecrets(contextSecrets, async () => {
          for (let index = 0; index < 400; index += 1) {
            await Promise.resolve();
            expect(() =>
              logger.info(
                {
                  nested: { value: withSecrets(), list: [withSecrets(), 42, null, true] },
                  err: new Error(withSecrets()),
                  count: index,
                },
                withSecrets(),
              ),
            ).not.toThrow();
          }
        });

        expect(lines).toHaveLength(400);
        for (const line of lines) {
          const parsed = JSON.parse(line);
          expect(parsed.level).toBe(30);
          expect(typeof parsed.count).toBe('number');
          for (const value of stringValues(parsed)) {
            for (const secret of allSecrets) {
              expect(value).not.toContain(secret);
            }
          }
        }
      },
    );
  });

  describe('malformed lines', () => {
    it.each([
      '',
      '\n',
      'not json at all',
      '"unterminated',
      '{"msg":"dangling backslash \\',
      '{"msg":"bad \\x escape"}\n',
      '{"msg":"short unicode \\u12"}\n',
      '{"msg":"lone quote " inside"}\n',
      '}{"]["',
      '\\\\\\"',
    ])('does not throw on %j', (line) => {
      const redact = createSecretRedactor({ secrets: [mockSecret] });

      expect(() => redact(line)).not.toThrow();
    });

    it('keeps a line valid JSON when one of its values is not', () => {
      const redact = createSecretRedactor({ secrets: [mockSecret] });

      const line = redact(`{"level":30,"msg":"bad \\x ${mockSecret}","nested":{"ok":"kept"}}\n`);

      expect(JSON.parse(line)).toEqual({ level: 30, msg: '[Redacted]', nested: { ok: 'kept' } });
    });
  });

  describe('unexpected failures', () => {
    afterEach(() => {
      vi.restoreAllMocks();
    });

    it('writes a redaction failed line instead of throwing out of the log call', () => {
      const { logger, lines } = createCapturingLogger({ secrets: [mockSecret] });
      vi.spyOn(String.prototype, 'matchAll').mockImplementation(() => {
        throw new Error('matching exploded');
      });

      expect(() => logger.info(`leaking ${mockSecret}`)).not.toThrow();

      expect(lines).toHaveLength(1);
      expect(lines[0]).toMatch(/\n$/);
      expect(lines[0]).not.toContain(mockSecret);
      const line = JSON.parse(lines[0] ?? '');
      expect(line.level).toBe(50);
      expect(line.msg).toBe('Log line replaced: secret redaction failed');
      expect(typeof line.time).toBe('number');
    });

    it('points at the log call and what broke, without the message or the secret', () => {
      const { logger, lines } = createCapturingLogger({ secrets: [mockSecret] });
      vi.spyOn(String.prototype, 'matchAll').mockImplementation(() => {
        throw new Error(`matching exploded on ${mockSecret}`);
      });
      class UserSyncService {
        public syncUser(): void {
          logger.info(`syncing ${mockSecret}`);
        }
      }

      new UserSyncService().syncUser();

      expect(lines[0]).not.toContain(mockSecret);
      expect(lines[0]).not.toContain('matching exploded');
      const line = JSON.parse(lines[0] ?? '');
      expect(line.original_level).toBe(30);
      expect(typeof line.original_time).toBe('number');
      expect(line.logged_from[0]).toMatch(
        /^UserSyncService\.syncUser \(.*redact-secrets\.resilience\.spec\.ts:\d+:\d+\)$/,
      );
      expect(line.logged_from.join('\n')).not.toMatch(/node_modules/);
      expect(line.err.name).toBe('Error');
      expect(line.err.stack.length).toBeGreaterThan(0);
      expect(line.err.stack[0]).toMatch(/redact-secrets\.resilience\.spec\.ts:\d+:\d+/);
    });

    it('keeps the trace and request ids of the original line', () => {
      const { logger, lines } = createCapturingLogger({ secrets: [mockSecret] });
      vi.spyOn(String.prototype, 'matchAll').mockImplementation(() => {
        throw new Error('matching exploded');
      });
      const traceId = '4bf92f3577b34da6a3ce929d0e0e4736';

      logger
        .child({
          trace_id: traceId,
          span_id: '00f067aa0ba902b7',
          req: { id: 'trace_01h455vb4pex5vsknk084sn02q' },
        })
        .info('traced');

      const line = JSON.parse(lines[0] ?? '');
      expect(line.trace_id).toBe(traceId);
      expect(line.span_id).toBe('00f067aa0ba902b7');
      expect(line.req_id).toBe('trace_01h455vb4pex5vsknk084sn02q');
    });

    it('drops ids of the original line that are not in their expected format', () => {
      const { logger, lines } = createCapturingLogger({ secrets: [mockSecret] });
      vi.spyOn(String.prototype, 'matchAll').mockImplementation(() => {
        throw new Error('matching exploded');
      });

      logger.child({ trace_id: mockSecret, req: { id: mockSecret } }).info('traced');

      expect(lines[0]).not.toContain(mockSecret);
      const line = JSON.parse(lines[0] ?? '');
      expect(line).not.toHaveProperty('trace_id');
      expect(line).not.toHaveProperty('req_id');
    });

    it('falls back to a minimal line when describing the failure fails too', () => {
      const { logger, lines } = createCapturingLogger({ secrets: [mockSecret] });
      vi.spyOn(String.prototype, 'matchAll').mockImplementation(() => {
        throw new Error('matching exploded');
      });
      vi.spyOn(Error, 'captureStackTrace').mockImplementation(() => {
        throw new Error('stack exploded');
      });
      const stackTraceLimit = Error.stackTraceLimit;

      expect(() => logger.info(`leaking ${mockSecret}`)).not.toThrow();

      expect(Object.keys(JSON.parse(lines[0] ?? '')).sort()).toEqual(['level', 'msg', 'time']);
      expect(lines[0]).toMatch(/\n$/);
      expect(Error.stackTraceLimit).toBe(stackTraceLimit);
    });

    it('keeps logging normally after a failed line', () => {
      const { logger, lines } = createCapturingLogger({ secrets: [mockSecret] });
      vi.spyOn(String.prototype, 'matchAll').mockImplementationOnce(() => {
        throw new Error('matching exploded');
      });

      logger.info('first');
      logger.info(`second ${mockSecret}`);

      expect(lines.map((line) => JSON.parse(line).msg)).toEqual([
        'Log line replaced: secret redaction failed',
        'second [Redacted]',
      ]);
    });

    it('ignores secrets that are not strings at runtime', () => {
      const notStrings = [undefined, null, 12345678, { value: mockSecret }] as unknown as string[];
      const { logger, lines } = createCapturingLogger({ secrets: [...notStrings, mockSecret] });

      runWithLogSecrets(notStrings, () => logger.info(`value ${mockSecret}`));

      expect(JSON.parse(lines[0] ?? '').msg).toBe('value [Redacted]');
    });
  });

  describe('consumer patterns', () => {
    it.each([
      ['an empty match', /(?:)/dg, 'tenant value xyz'],
      ['an anchored match', /^/dg, 'tenant value xyz'],
      ['an empty secret group', /tenant(?<secret>)/dg, 'tenant value xyz'],
      ['an optional match', /z*/dg, 'tenant value xy[Redacted]'],
    ])('does not throw or loop on %s', (_name, pattern, expected) => {
      const { logger, lines } = createCapturingLogger({
        patterns: [pattern],
        defaultPatterns: false,
      });

      logger.info('tenant value xyz');

      expect(JSON.parse(lines[0] ?? '').msg).toBe(expected);
    });

    it('redacts from the start of every line whatever lastIndex the caller left on its regex', () => {
      const pattern = /tenant-key:(?<secret>\w+)/dg;
      const { logger, lines } = createCapturingLogger({ patterns: [pattern] });
      pattern.lastIndex = 5;

      logger.info('tenant-key:first');
      logger.info('tenant-key:second');

      expect(lines.map((line) => JSON.parse(line).msg)).toEqual([
        'tenant-key:[Redacted]',
        'tenant-key:[Redacted]',
      ]);
      expect(pattern.lastIndex).toBe(5);
    });
  });

  describe('default patterns', () => {
    it.each([
      'Refreshing token for user',
      'token value expired',
      'Basic auth failed',
      'a bearer of bad news',
    ])('leaves ordinary text alone: %j', (message) => {
      const { logger, lines } = createCapturingLogger();

      logger.info(message);

      expect(JSON.parse(lines[0] ?? '').msg).toBe(message);
    });
  });

  describe('secret contents', () => {
    it.each([
      ['replacement tokens', "$&$`$'$$(.*)"],
      ['regex metacharacters', '.*+?^$}{()|[]\\'],
      ['an emoji and accents', 'clé-😀-secrète'],
      ['a lone surrogate', 'lone-\ud800-surrogate'],
      ['a newline and tab', 'multi\nline\tsecret'],
    ])('redacts a secret with %s', (_name, secret) => {
      const { logger, lines } = createCapturingLogger({ secrets: [secret] });

      logger.info({ detail: `before ${secret} after` }, `start ${secret} end`);

      const line = JSON.parse(lines[0] ?? '');
      expect(line.msg).toBe('start [Redacted] end');
      expect(line.detail).toBe('before [Redacted] after');
    });

    it('redacts a secret in a 1 MB value', () => {
      const { logger, lines } = createCapturingLogger({ secrets: [mockSecret] });
      const padding = 'x'.repeat(512 * 1024);

      logger.info(`${padding}${mockSecret}${padding}`);

      const message: string = JSON.parse(lines[0] ?? '').msg;
      expect(message).not.toContain(mockSecret);
      expect(message).toHaveLength(padding.length * 2 + '[Redacted]'.length);
    });
  });

  describe('where secrets appear', () => {
    it('redacts child logger bindings', () => {
      const { logger, lines } = createCapturingLogger({ secrets: [mockSecret] });

      logger.child({ upstreamKey: mockSecret }).info('bound');

      expect(JSON.parse(lines[0] ?? '').upstreamKey).toBe('[Redacted]');
    });

    it('redacts the cause of an error', () => {
      const { logger, lines } = createCapturingLogger({ secrets: [mockSecret] });

      logger.error(
        { err: new Error('outer', { cause: new Error(`inner ${mockSecret}`) }) },
        'failed',
      );

      expect(lines[0]).not.toContain(mockSecret);
      expect(JSON.parse(lines[0] ?? '').level).toBe(50);
    });
  });

  describe('context secrets', () => {
    it('keeps concurrent contexts apart', async () => {
      const { logger, lines } = createCapturingLogger();

      await Promise.all([
        runWithLogSecrets(['first-context-secret'], async () => {
          await sleep(5);
          logger.info('first-context-secret second-context-secret');
        }),
        runWithLogSecrets(['second-context-secret'], async () => {
          await sleep(1);
          logger.info('first-context-secret second-context-secret');
        }),
      ]);

      expect(lines.map((line) => JSON.parse(line).msg).sort()).toEqual(
        ['[Redacted] second-context-secret', 'first-context-secret [Redacted]'].sort(),
      );
    });

    it('follows timers and promise chains', async () => {
      const { logger, lines } = createCapturingLogger();

      await runWithLogSecrets(['timer-context-secret'], async () => {
        await sleep(1);
        await new Promise<void>((resolve) =>
          setImmediate(() => {
            logger.info('timer-context-secret');
            resolve();
          }),
        );
      });

      expect(JSON.parse(lines[0] ?? '').msg).toBe('[Redacted]');
    });

    it('returns what the callback returns and rethrows what it throws', async () => {
      expect(runWithLogSecrets(['returned-secret-1'], () => 42)).toBe(42);
      await expect(
        runWithLogSecrets(['rejected-secret-1'], async () => {
          throw new Error('callback failed');
        }),
      ).rejects.toThrow('callback failed');
    });
  });
});
