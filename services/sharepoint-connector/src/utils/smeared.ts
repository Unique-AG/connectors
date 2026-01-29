import {
  LOGS_DIAGNOSTICS_DATA_POLICY_ENV_NAME,
  LogsDiagnosticDataPolicy,
} from '../config/app.config';
import { smear } from './logging.util';

/**
 * Wraps diagnostic data that we want visible in dev but smeared in production.
 *
 * Use for site IDs, user IDs, paths - values that help debugging but shouldn't leak in prod logs.
 * For actual secrets (passwords, keys), use Redacted instead - that NEVER shows the value.
 *
 * @example
 * const siteId = createSmeared('bd9c85ee-998f-4665-9c44');
 * logger.log(`Site: ${siteId}`); // "Site: ********-****-9c44"
 * api.fetchSite(siteId.value); // Always uses the real value
 */
export class Smeared {
  private readonly _value: string;
  private readonly _active: boolean;

  public constructor(value: string, active: boolean) {
    this._value = value;
    this._active = active;
  }

  public get value(): string {
    return this._value;
  }

  public get active(): boolean {
    return this._active;
  }

  public toString(): string {
    return this._active ? smear(this._value) : this._value;
  }

  public toJSON(): string {
    return this.toString();
  }
}

export function isSmearingActiveFromEnv(): boolean {
  return process.env[LOGS_DIAGNOSTICS_DATA_POLICY_ENV_NAME] !== LogsDiagnosticDataPolicy.DISCLOSE;
}

export function createSmeared(value: string): Smeared {
  return new Smeared(value, isSmearingActiveFromEnv());
}
