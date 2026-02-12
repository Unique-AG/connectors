export function asAllOptions<T extends string>() {
  return <U extends readonly T[]>(
    arr: U & ([T] extends [U[number]] ? unknown : 'Missing required option'),
  ): U => arr;
}
