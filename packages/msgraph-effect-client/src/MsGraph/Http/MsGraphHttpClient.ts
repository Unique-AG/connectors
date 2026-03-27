import { Context, Effect, Schema, Stream } from "effect"
import type { MsGraphError } from "../Errors/errors"

export interface MsGraphHttpClient {
  readonly get: <A, I>(
    path: string,
    schema: Schema.Schema<A, I>,
  ) => Effect.Effect<A, MsGraphError>

  readonly post: <A, I>(
    path: string,
    body: unknown,
    schema: Schema.Schema<A, I>,
  ) => Effect.Effect<A, MsGraphError>

  readonly postVoid: (
    path: string,
    body: unknown,
  ) => Effect.Effect<void, MsGraphError>

  readonly patch: <A, I>(
    path: string,
    body: unknown,
    schema: Schema.Schema<A, I>,
    headers?: Record<string, string>,
  ) => Effect.Effect<A, MsGraphError>

  readonly delete: (
    path: string,
    headers?: Record<string, string>,
  ) => Effect.Effect<void, MsGraphError>

  readonly stream: (
    path: string,
  ) => Effect.Effect<Stream.Stream<Uint8Array, MsGraphError>, MsGraphError>
}

export const MsGraphHttpClient = Context.GenericTag<MsGraphHttpClient>(
  "MsGraph/HttpClient",
)
