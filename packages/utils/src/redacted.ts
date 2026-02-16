export class Redacted<T> {
  public constructor(public readonly value: T) {}

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
    return this.toString();
  }
}
