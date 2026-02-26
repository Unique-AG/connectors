// Utility function which helps exhausting string tuples for example you have the following type.
// export type FileAccess = 'Read' | 'Write' | 'Manage'
// and you want to have all the enum values in an array and trigger a typescript error
// if one of them is missing from that array, we can achieve that with this function.
// const FILE_ACCESS_OPTIONS = asAllOptions<FileAccess>()([
//    'Read',
//    'Write',
//    'Manage'
// ])
// This construct forces typescript to check at build time that all the posible values
// from the string tuple are present in the array passed to asAllOptions<FileAccess>()
export function asAllOptions<T extends string>() {
  return <U extends readonly T[]>(
    arr: U & ([T] extends [U[number]] ? unknown : 'Missing required option'),
  ): U => arr;
}
