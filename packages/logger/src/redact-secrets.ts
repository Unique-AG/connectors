import assert from 'node:assert';
import { AsyncLocalStorage } from 'node:async_hooks';
import type { IncomingMessage, ServerResponse } from 'node:http';

/** Shorter values are skipped: replacing them would hit ordinary words and numbers. */
export const MIN_SECRET_LENGTH = 8;

const REDACTED = '[Redacted]';

/*
 * Applied to every log line unless `defaultPatterns` is false, and exported one by one so a consumer
 * that opts out can pick its own. When a pattern has a `secret` group, only that group is replaced,
 * so the context around it (`Bearer `, `password=`) stays readable. A pattern that can fail after a
 * long run starts only where that run starts: one that tried again inside the run would take seconds
 * on a large value.
 */

// A credential has a digit, an inner capital or a symbol, or is too long to be a word, so prose such
// as "Basic authentication failed" keeps its words.
export const AUTHORIZATION_SCHEME_PATTERN =
  /\b(?:Bearer|Basic)\s+(?<secret>(?=[A-Za-z0-9\-._~+/]+[0-9A-Z_~+/=]|[A-Za-z0-9\-._~+/]{20})[A-Za-z0-9\-._~+/]{8,}=*)/dg;
export const JWT_PATTERN =
  /(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/dg;
export const API_KEY_PATTERN = /\b(?:x-)?api[-_]?key\s*[=:]\s*(?<secret>[^\s&,;"']+)/dgi;
export const CREDENTIAL_PARAMETER_PATTERN =
  /\b(?:access[-_]?token|refresh[-_]?token|id[-_]?token|client[-_]?secret|password|passwd|secret|token)=(?<secret>[^\s&,;"']+)/dgi;
export const URL_CREDENTIALS_PATTERN =
  /(?<![a-z0-9+.-])[a-z][a-z0-9+.-]*:\/\/[^/\s:@]+:(?<secret>[^/\s@]+)@/dgi;
export const PRIVATE_KEY_PATTERN =
  /-----BEGIN [A-Z ]*PRIVATE KEY-----(?:(?!-----BEGIN )[\s\S])*?-----END [A-Z ]*PRIVATE KEY-----/dg;
export const SK_PREFIXED_KEY_PATTERN = /\bsk-[A-Za-z0-9_-]{20,}/dg;
export const GITHUB_TOKEN_PATTERN = /\bgh[pousr]_[A-Za-z0-9]{36,}/dg;
export const SLACK_TOKEN_PATTERN = /\bxox[abprs]-[A-Za-z0-9-]{10,}/dg;
export const AWS_ACCESS_KEY_ID_PATTERN = /\bAKIA[0-9A-Z]{16}\b/dg;

export const DEFAULT_SECRET_PATTERNS: readonly RegExp[] = [
  AUTHORIZATION_SCHEME_PATTERN,
  JWT_PATTERN,
  API_KEY_PATTERN,
  CREDENTIAL_PARAMETER_PATTERN,
  URL_CREDENTIALS_PATTERN,
  PRIVATE_KEY_PATTERN,
  SK_PREFIXED_KEY_PATTERN,
  GITHUB_TOKEN_PATTERN,
  SLACK_TOKEN_PATTERN,
  AWS_ACCESS_KEY_ID_PATTERN,
];

// A JSON string literal, and the colon after it when it is an object key.
const JSON_STRING = /("(?:[^"\\]|\\.)*")(\s*:)?/g;

// pino writes the line's own `msg` last, after any nested in the logged object.
const MSG = /"msg":("(?:[^"\\]|\\.)*")/g;

// The secrets of one `runWithLogSecrets` call or request. Everything that runs in it shares this
// object, so a secret `addLogSecrets` adds late reaches all of it, including the lines logged after
// the call that added it returns or throws.
interface LogScope {
  readonly parent: LogScope | undefined;
  // The variants to replace, longest first, already expanded by `secretVariants`.
  secrets: readonly string[];
  // Why secrets of this scope could not be read, as JSON added to every line logged in it.
  failure?: string;
}

const logScope = new AsyncLocalStorage<LogScope>();

export interface SecretRedactionOptions {
  /** Known secret values, such as API keys from env. Values under `MIN_SECRET_LENGTH` are skipped. */
  secrets?: readonly string[];
  /**
   * Added to `DEFAULT_SECRET_PATTERNS`. Each needs the `g` and `d` flags. A `secret` named group
   * narrows what is replaced.
   */
  patterns?: readonly RegExp[];
  /** `false` drops `DEFAULT_SECRET_PATTERNS`, leaving only `patterns`, which can pick from them. */
  defaultPatterns?: boolean;
}

/**
 * Builds the pino `hooks.streamWrite` hook. It replaces known secrets, the current context's
 * secrets and pattern matches inside every JSON string value of the serialized line, and the
 * secrets alone inside keys. Structure is never touched and every changed string is re-encoded, so
 * the line always stays valid JSON. It never throws: a line it cannot redact is replaced by one that
 * says so.
 */
export function createSecretRedactor({
  secrets = [],
  patterns = [],
  defaultPatterns = true,
}: SecretRedactionOptions = {}): (line: string) => string {
  const knownSecrets = secretVariants(secrets);
  patterns.forEach(assertPatternFlags);
  // Copies, so a `lastIndex` left on the caller's regex never shifts where matching starts. Each
  // keeps the class of its original, and with it any matching that class overrides.
  const allPatterns = [...(defaultPatterns ? DEFAULT_SECRET_PATTERNS : []), ...patterns].map(
    (pattern) => {
      const copy = new RegExp(pattern);
      Object.setPrototypeOf(copy, Object.getPrototypeOf(pattern));
      return copy;
    },
  );

  const secretsIn = (scope: LogScope | undefined): readonly string[] => {
    const scoped = scopeSecrets(scope);
    return scoped.length === 0 ? knownSecrets : longestFirst([...knownSecrets, ...scoped]);
  };
  const replacePatterns = (text: string): string => allPatterns.reduce(redactPattern, text);

  const redactLine = (line: string, secrets: readonly string[]): string =>
    line.replace(JSON_STRING, (token: string, literal: string, keyColon: string | undefined) => {
      const text = decodeJsonString(literal);
      if (text === undefined) {
        return keyColon === undefined ? JSON.stringify(REDACTED) : token;
      }
      if (keyColon !== undefined) {
        const redactedKey = replaceSecrets(text, secrets);
        return redactedKey === text ? token : `${JSON.stringify(redactedKey)}${keyColon}`;
      }
      const redacted = replacePatterns(replaceSecrets(text, secrets));
      return redacted === text ? token : JSON.stringify(redacted);
    });

  // What can still be shown of a message when redacting its line failed. Replacing the secrets
  // cannot fail, the patterns are what may have.
  const salvage = (text: string, scope: LogScope | undefined): string => {
    const withoutSecrets = replaceSecrets(text, secretsIn(scope));
    try {
      return replacePatterns(withoutSecrets);
    } catch {
      return withoutSecrets;
    }
  };

  // The hook runs inside the log call, so a throw would fail the caller's request, and writing
  // the line as it is could leak the secret.
  const hook = (line: string): string => {
    const scope = logScope.getStore();
    try {
      return withFailure(redactLine(line, secretsIn(scope)), scopeFailure(scope));
    } catch (error) {
      return redactionFailedLine(line, error, hook, (text) => salvage(text, scope));
    }
  };
  return hook;
}

/** Runs `callback` with `secrets` redacted from every line it logs, on top of the outer ones. */
export function runWithLogSecrets<T>(secrets: readonly string[], callback: () => T): T {
  return logScope.run(
    scopeWith(() => secrets),
    callback,
  );
}

/**
 * Redacts `secrets` from every line logged until the innermost `runWithLogSecrets` call or
 * `redactRequestSecrets` request ends, also after the caller returns or throws. For a secret read
 * partway through, such as the caller's token loaded from a database while the request is
 * handled. Outside such a scope it does nothing. It never throws: when it fails, the lines of the
 * scope name the error in `log_secrets_failed`.
 */
export function addLogSecrets(secrets: readonly string[]): void {
  const scope = logScope.getStore();
  if (scope === undefined) {
    return;
  }
  try {
    scope.secrets = longestFirst([...scope.secrets, ...secretVariants(secrets)]);
  } catch (error) {
    scope.failure = failureJson(error);
  }
}

/**
 * Middleware that redacts what `secretsOf` returns for a request, such as its bearer token or API
 * key, from every line logged while the request is handled. An MCP tool call arrives as a request,
 * so this covers tool calls too. When `secretsOf` throws, the request still runs and every line it
 * logs names the error in `log_secrets_failed`.
 */
export function redactRequestSecrets<Request extends IncomingMessage>(
  secretsOf: (request: Request) => readonly string[],
): (request: Request, response: ServerResponse, next: () => void) => void {
  return (request, _response, next) =>
    logScope.run(
      scopeWith(() => secretsOf(request)),
      next,
    );
}

// Secrets that cannot be read must not fail the caller: its lines are still written, redacted for
// every other secret and naming the failure.
function scopeWith(secretsOf: () => readonly string[]): LogScope {
  const parent = logScope.getStore();
  try {
    return { parent, secrets: secretVariants(secretsOf()) };
  } catch (error) {
    return { parent, secrets: [], failure: failureJson(error) };
  }
}

function scopeSecrets(scope: LogScope | undefined): readonly string[] {
  return scope === undefined ? [] : [...scopeSecrets(scope.parent), ...scope.secrets];
}

function scopeFailure(scope: LogScope | undefined): string | undefined {
  return scope === undefined ? undefined : (scope.failure ?? scopeFailure(scope.parent));
}

function failureJson(error: unknown): string {
  try {
    return JSON.stringify(errorFields(error));
  } catch {
    return JSON.stringify({ name: 'unknown' });
  }
}

// A pino line always opens with `{"level":`, so the field goes in front of it.
function withFailure(line: string, failure: string | undefined): string {
  return failure === undefined || !line.startsWith('{"')
    ? line
    : `{"log_secrets_failed":${failure},${line.slice(1)}`;
}

/**
 * The line written in place of one that could not be redacted. It points at the log call and at
 * what broke, from frames, numbers and fixed-format ids only: the error's message and the line's
 * strings can quote the secret. The message is kept as `salvage` returns it. It does not log, so it
 * cannot loop, and it cannot throw.
 */
function redactionFailedLine(
  line: string,
  error: unknown,
  hook: (line: string) => string,
  salvage: (text: string) => string,
): string {
  const failed = { level: 50, time: Date.now(), msg: 'Log line replaced: secret redaction failed' };
  try {
    return `${JSON.stringify({
      ...failed,
      ...originalFields(line),
      ...originalMsg(line, salvage),
      logged_from: callerFrames(hook),
      err: errorFields(error),
    })}\n`;
  } catch {
    return `${JSON.stringify(failed)}\n`;
  }
}

const MAX_FRAMES = 5;
// A V8 frame ends in its location. A message line that happens to start with `at` does not.
const STACK_FRAME = /^\s+at (.+:\d+:\d+\)?)$/;
const ORIGINAL_FIELDS: ReadonlyArray<readonly [string, RegExp]> = [
  ['original_level', /"level":(\d+)/],
  ['original_time', /"time":(\d+)/],
  ['context', /"context":("[A-Za-z0-9_.$-]{1,100}")/],
  ['trace_id', /"trace_id":("[0-9a-f]{32}")/],
  ['span_id', /"span_id":("[0-9a-f]{16}")/],
  ['req_id', /"req":\{"id":(\d+|"[0-9a-f]{32}"|"[a-z_]+_[0-9a-z]{26}")/],
];

// Read from the raw line, which may be what broke, and only in formats that cannot hold a secret.
function originalFields(line: string): Record<string, unknown> {
  return Object.fromEntries(
    ORIGINAL_FIELDS.flatMap(([name, pattern]) => {
      const value = pattern.exec(line)?.[1];
      return value === undefined ? [] : [[name, JSON.parse(value)]];
    }),
  );
}

function originalMsg(line: string, salvage: (text: string) => string): { original_msg?: string } {
  try {
    const literal = [...line.matchAll(MSG)].at(-1)?.[1];
    const text = literal === undefined ? undefined : decodeJsonString(literal);
    return text === undefined ? {} : { original_msg: salvage(text) };
  } catch {
    return {};
  }
}

// The frames of the log call, above pino and any other library between it and the caller.
function callerFrames(hook: (line: string) => string): string[] {
  const limit = Error.stackTraceLimit;
  const holder: { stack?: string } = {};
  try {
    Error.stackTraceLimit = 30;
    Error.captureStackTrace(holder, hook);
  } finally {
    Error.stackTraceLimit = limit;
  }
  return stackFrames(holder.stack, (frame) => !/node_modules|node:internal/.test(frame));
}

function stackFrames(
  stack: string | undefined,
  keep: (frame: string) => boolean = () => true,
): string[] {
  return (stack ?? '')
    .split('\n')
    .flatMap((line) => STACK_FRAME.exec(line)?.slice(1, 2) ?? [])
    .filter(keep)
    .slice(0, MAX_FRAMES);
}

function errorFields(error: unknown): { name: string; stack: string[] } {
  return {
    name: errorName(error),
    stack: stackFrames(error instanceof Error ? error.stack : undefined),
  };
}

// The constructor's name, not `error.name`, which code can set to anything.
function errorName(error: unknown): string {
  return error instanceof Error ? error.constructor.name : typeof error;
}

// Undefined for a literal that is not valid JSON, which the caller redacts whole rather than
// throwing out of the log call or writing it as it is.
function decodeJsonString(literal: string): string | undefined {
  if (!literal.includes('\\')) {
    return literal.slice(1, -1);
  }
  try {
    return JSON.parse(literal);
  } catch {
    return undefined;
  }
}

// Each secret as written and URL-encoded, as a query string carries it.
function secretVariants(secrets: readonly string[]): string[] {
  return longestFirst(
    secrets
      // A consumer reading an absent header passes `undefined` whatever the types say.
      .filter((secret) => typeof secret === 'string' && secret.length >= MIN_SECRET_LENGTH)
      .flatMap((secret) => [secret, ...urlEncoded(secret)]),
  );
}

// `encodeURIComponent` throws on a lone surrogate, which no URL can carry anyway.
function urlEncoded(secret: string): string[] {
  try {
    return [encodeURIComponent(secret)];
  } catch {
    return [];
  }
}

function replaceSecrets(text: string, secrets: readonly string[]): string {
  return secrets.reduce((redacted, secret) => redacted.replaceAll(secret, REDACTED), text);
}

// Longest first, so a secret that contains another is replaced whole.
function longestFirst(secrets: readonly string[]): string[] {
  return [...new Set(secrets)].sort((a, b) => b.length - a.length);
}

function redactPattern(text: string, pattern: RegExp): string {
  const spans = [...text.matchAll(pattern)]
    .map((match) => match.indices?.groups?.secret ?? match.indices?.[0])
    .filter((span): span is [number, number] => span !== undefined && span[0] < span[1]);
  if (spans.length === 0) {
    return text;
  }
  const ends = [0, ...spans.map(([, end]) => end)];
  const kept = spans.map(([start], index) => text.slice(ends[index], start));
  return `${kept.join(REDACTED)}${REDACTED}${text.slice(ends.at(-1))}`;
}

// `g` replaces every match, and `d` exposes where the `secret` group matched.
function assertPatternFlags(pattern: RegExp): void {
  const missing = ['g', 'd'].filter((flag) => !pattern.flags.includes(flag)).join('');
  assert.ok(
    missing === '',
    `Secret pattern ${pattern} is missing the "${missing}" flag(s); write it as /${pattern.source}/${pattern.flags}${missing}`,
  );
}
