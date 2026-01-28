export class Redacted<T> {
  private readonly _value: T;

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
    return '[Redacted]';
  }
}
