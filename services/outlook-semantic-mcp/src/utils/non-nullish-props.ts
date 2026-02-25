export type NonNullishProps<T, NonNullItems extends keyof T> = Omit<T, NonNullItems> &
  Required<{
    [key in NonNullItems]-?: Exclude<T[key], null | undefined>;
  }>;
