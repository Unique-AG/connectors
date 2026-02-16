import { LogsDiagnosticDataPolicy } from '../config/app.config';
import { smear } from './logging.util';

/**
 * Wraps diagnostic data that we want visible in dev but smeared in production.
 *
 * Use for emails, usernames, IDs - values that help debugging but shouldn't leak in prod logs.
 * For actual secrets (passwords, keys, tokens), use Redacted instead - that NEVER shows the value.
 *
 * @example
 * const email = createSmeared('admin@acme.com');
 * logger.log(`User: ${email}`); // "User: *****@****.com"
 * api.call(email.value); // Always uses the real value
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
}

export function isSmearingActive(): boolean {
  return process.env.LOGS_DIAGNOSTICS_DATA_POLICY !== LogsDiagnosticDataPolicy.DISCLOSE;
}

export function createSmeared(value: string): Smeared {
  return new Smeared(value, isSmearingActive());
}
