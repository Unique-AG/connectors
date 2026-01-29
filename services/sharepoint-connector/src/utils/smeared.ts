import {
  LOGS_DIAGNOSTICS_DATA_POLICY_ENV_NAME,
  LogsDiagnosticDataPolicy,
} from '../config/app.config';
import { smear } from './logging.util';

export class Smeared<T extends string = string> {
  private readonly _value: T;
  private readonly _active: boolean;

  public constructor(value: T, active: boolean) {
    this._value = value;
    this._active = active;
  }

  public get value(): T {
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

export function createSmeared<T extends string = string>(value: T): Smeared<T> {
  return new Smeared(value, isSmearingActiveFromEnv());
}
