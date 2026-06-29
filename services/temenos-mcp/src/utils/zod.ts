import { Redacted } from '@unique-ag/utils';
import z from 'zod/v4';

export const redacted = <S extends z.core.$ZodType>(schema: S) =>
  z.codec(schema, z.instanceof(Redacted<z.output<S>>), {
    decode: (value) => new Redacted(value),
    encode: (redacted) => redacted.value,
  });

export const enabledDisabledBoolean = (
  description: string,
  defaultValue: 'enabled' | 'disabled' = 'enabled',
): z.ZodPipe<
  z.ZodDefault<
    z.ZodEnum<{
      enabled: 'enabled';
      disabled: 'disabled';
    }>
  >,
  z.ZodTransform<boolean, 'enabled' | 'disabled'>
> =>
  z
    .enum(['enabled', 'disabled'])
    .default(defaultValue)
    .describe(description)
    .transform((value) => value === 'enabled');
