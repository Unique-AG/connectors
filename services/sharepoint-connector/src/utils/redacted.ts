import { redact } from './logging.util';

export class Redacted<T> {
  private static _conceal = true;
  private readonly _value: T;

  public static setConceal(conceal: boolean) {
    Redacted._conceal = conceal;
  }

  public static getConceal(): boolean {
    return Redacted._conceal;
  }

  public constructor(value: T) {
    this._value = value;
  }

  public get value(): T {
    return this._value;
  }

  /**
   * Always returns [Redacted] for safety in string concatenations and templates.
   */
  public toString() {
    return '[Redacted]';
  }

  /**
   * Used for structured logging (Pino/JSON.stringify).
   * Always redacts; never discloses raw values.
   */
  public toJSON() {
    if (typeof this._value === 'string') {
      return redact(this._value);
    }
    return '[Redacted]';
  }
}
