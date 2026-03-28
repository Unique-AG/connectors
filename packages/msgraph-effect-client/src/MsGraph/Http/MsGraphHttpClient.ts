import { Effect, Schema, ServiceMap, Stream } from 'effect';
import type { MsGraphError } from '../Errors/errors';

export class MsGraphHttpClient extends ServiceMap.Service<
  MsGraphHttpClient,
  {
    readonly get: <A>(path: string, schema: Schema.Schema<A>) => Effect.Effect<A, MsGraphError>;

    readonly post: <A>(
      path: string,
      body: unknown,
      schema: Schema.Schema<A>,
    ) => Effect.Effect<A, MsGraphError>;

    readonly postVoid: (path: string, body: unknown) => Effect.Effect<void, MsGraphError>;

    readonly patch: <A>(
      path: string,
      body: unknown,
      schema: Schema.Schema<A>,
      headers?: Record<string, string>,
    ) => Effect.Effect<A, MsGraphError>;

    readonly delete: (
      path: string,
      headers?: Record<string, string>,
    ) => Effect.Effect<void, MsGraphError>;

    readonly stream: (
      path: string,
    ) => Effect.Effect<Stream.Stream<Uint8Array, MsGraphError>, MsGraphError>;
  }
>()('MsGraph/Http/MsGraphHttpClient') {}
