export const LogsDiagnosticDataPolicy = {
  CONCEAL: 'conceal',
  DISCLOSE: 'disclose',
} as const;

/**
 * Wraps diagnostic data that we want visible in dev but smeared in production.
 *
 * Use for names, emails, paths - values that help debugging but shouldn't leak in prod logs.
 * For actual secrets (passwords, keys), use Redacted instead - that NEVER shows the value.
 *
 * @example
 * const name = createSmeared('John Smith');
 * logger.log(`User: ${name}`); // "User: ******mith"
 * api.fetchUser(name.value); // Always uses the real value
 */
export class Smeared {
  public constructor(
    public readonly value: string,
    public readonly active: boolean,
    public readonly smearEnd: boolean = false,
  ) {}

  public toString(): string {
    return this.active ? smear(this.value, { smearEnd: this.smearEnd }) : this.value;
  }

  public toJSON(): string {
    return this.toString();
  }

  public transform(transformer: (value: string) => string): Smeared {
    return new Smeared(transformer(this.value), this.active, this.smearEnd);
  }
}

export function isSmearingActive(): boolean {
  return process.env.LOGS_DIAGNOSTICS_DATA_POLICY !== LogsDiagnosticDataPolicy.DISCLOSE;
}

export function createSmeared(value: string): Smeared {
  return new Smeared(value, isSmearingActive());
}

export function smearPath(path: Smeared) {
  return path.value
    .split('/')
    .map((segment) => {
      // This thing preserves multiple slashes / trailing slashes.
      if (segment.length === 0) {
        return '';
      }
      return new Smeared(segment, path.active);
    })
    .join('/');
}

const SMEAR_CONSTS = {
  error: '__erroneous__',
  totallySmeared: '[Smeared]',
};

export function smearEmail(email: Smeared) {
  const emailParts = email.value.split('@');

  return emailParts
    .map((part, index) => {
      if (index + 1 === emailParts.length) {
        return new Smeared(part, email.active, true);
      }
      return new Smeared(part, email.active).toString();
    })
    .join('@');
}

/**
 * @description
 * Smear function should be used to obfuscate logs like emails / names basically details
 * which are not super sensitive but it's still usefull to see a small part of the origninal
 * string for debugging purpuses. For secrets always use Redacted.
 *
 * The smear function should not be used directly if something should be Smeared it should be
 * wrapped in Smeared class always. This function is exported only for testing purpuses
 *
 * @example
 * smear('password');        // "****word"
 * smear('mySecret123');     // "*******t123"
 * smear('hello', {leaveOver: 2});        // "***lo"
 * smear('ab');               // "[Smeared]"
 * smear(null);               // "__erroneous__"
 */
export function smear(
  text: string | null | undefined,
  options?: { leaveOver?: number; smearEnd?: boolean },
) {
  const leaveOver = options?.leaveOver ?? 4;
  const smearFront = options?.smearEnd ?? false;

  if (text === undefined || text === null) {
    return SMEAR_CONSTS.error;
  }
  if (!text.length || text.length <= leaveOver) {
    return SMEAR_CONSTS.totallySmeared;
  }

  const charsToSmear = text.length - leaveOver;
  if (charsToSmear < 3) {
    return SMEAR_CONSTS.totallySmeared;
  }

  const replaceRegex = /[a-zA-Z0-9_]/g;

  if (smearFront) {
    const start = text.substring(0, leaveOver);
    const toSmear = text.substring(leaveOver, text.length);
    return `${start}${toSmear.replaceAll(replaceRegex, '*')}`;
  }

  const end = text.substring(text.length - leaveOver, text.length);
  const toSmear = text.substring(0, text.length - leaveOver);
  return `${toSmear.replaceAll(replaceRegex, '*')}${end}`;
}
