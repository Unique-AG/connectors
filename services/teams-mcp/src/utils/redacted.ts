export class Redacted<T> {
  private readonly _value: T;

  public constructor(value: T) {
    this._value = value;
  }

  public get value(): T {
    return this._value;
  }

  public toString() {
    return '[Redacted]';
  }

  public toJSON() {
    return '[Redacted]';
  }
}
