export type NonNullishProps<T, NonNullItems extends keyof T> = Exclude<T, NonNullItems> &
  Required<{
    [key in NonNullItems]: Exclude<T[key], null | undefined>;
  }>;
