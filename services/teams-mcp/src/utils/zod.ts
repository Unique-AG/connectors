import z from 'zod/v4';
import { Redacted } from './redacted';

export const stringToURL = (opts?: string | z.core.$ZodURLParams) =>
  z.codec(z.url(opts), z.instanceof(URL), {
    decode: (urlString) => new URL(urlString),
    encode: (url) => url.href,
  });

export const redacted = <S extends z.core.$ZodType>(schema: S) =>
  z.codec(schema, z.instanceof(Redacted<z.output<S>>), {
    decode: (value) => new Redacted(value),
    encode: (redacted) => redacted.value,
  });
