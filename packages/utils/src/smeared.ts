import { smear } from './smear';

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
  ) {}

  public toString(): string {
    return this.active ? smear(this.value) : this.value;
  }

  public toJSON(): string {
    return this.toString();
  }

  public transform(transformer: (value: string) => string): Smeared {
    return new Smeared(transformer(this.value), this.active);
  }
}

export function isSmearingActive(): boolean {
  return process.env.LOGS_DIAGNOSTICS_DATA_POLICY !== LogsDiagnosticDataPolicy.DISCLOSE;
}

export function createSmeared(value: string): Smeared {
  return new Smeared(value, isSmearingActive());
}

export function smearPath(path: Smeared) {
  return path.value.split('/').map(createSmeared).join('/');
}
