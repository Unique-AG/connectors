import { fromString, typeid as libtypeid, parseTypeId, TypeID } from 'typeid-js';
import z from 'zod/v4';
import { Redacted } from './redacted';

export const json = <S extends z.core.$ZodType>(schema: S) =>
  z.codec(z.string(), schema, {
    decode: (jsonString, ctx) => {
      try {
        return JSON.parse(jsonString);
      } catch (err: unknown) {
        ctx.issues.push({
          code: 'invalid_format',
          format: 'json',
          input: jsonString,
          message: err instanceof Error ? err.message : String(err),
        });
        return z.NEVER;
      }
    },
    encode: (value, ctx) => {
      try {
        return JSON.stringify(value);
      } catch (err: unknown) {
        ctx.issues.push({
          code: 'invalid_format',
          format: 'json',
          input: String(value),
          message: err instanceof Error ? err.message : String(err),
        });
        return z.NEVER;
      }
    },
  });

export const typeid = <T extends string>(prefix?: T) =>
  z.codec(z.string(), z.instanceof(TypeID<T>), {
    decode(value, ctx) {
      try {
        const tid = fromString(value, prefix);
        const pid = parseTypeId(tid);
        return libtypeid(pid.prefix, pid.suffix);
      } catch (err) {
        ctx.issues.push({
          code: 'invalid_format',
          format: 'typeid',
          input: value,
          message: err instanceof Error ? err.message : String(err),
        });
        return z.NEVER;
      }
    },
    encode(value) {
      return value.toString();
    },
  });

export const stringToURL = (...opts: Parameters<typeof z.url>) =>
  z.codec(z.url(...opts), z.instanceof(URL), {
    decode: (urlString) => new URL(urlString),
    encode: (url) => url.href,
  });

export const isoDatetimeToDate = (...opts: Parameters<typeof z.iso.datetime>) =>
  z.codec(z.iso.datetime(...opts), z.date(), {
    decode: (isoString) => new Date(isoString),
    encode: (date) => date.toISOString(),
  });

export const redacted = <S extends z.core.$ZodType>(schema: S) =>
  z.codec(schema, z.instanceof(Redacted<z.output<S>>), {
    decode: (value) => new Redacted(value),
    encode: (redacted) => redacted.value,
  });
