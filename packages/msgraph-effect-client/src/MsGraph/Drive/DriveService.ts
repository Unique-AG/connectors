import { Context, Effect, Stream } from "effect"
import type {
  InvalidRequestError,
  QuotaExceededError,
  RateLimitedError,
  ResourceNotFoundError,
} from "../Errors/errors"
import type { DriveItem, SharingLink } from "../Schemas/DriveItem"
import type { ODataPageType, ODataParams } from "../Schemas/OData"

export interface DriveService {
  readonly listItems: (
    driveId: string,
    folderId?: string,
    params?: ODataParams<DriveItem>,
  ) => Effect.Effect<ODataPageType<DriveItem>, ResourceNotFoundError | RateLimitedError>

  readonly getItem: (
    driveId: string,
    itemId: string,
  ) => Effect.Effect<DriveItem, ResourceNotFoundError | RateLimitedError>

  readonly getByPath: (
    driveId: string,
    path: string,
  ) => Effect.Effect<DriveItem, ResourceNotFoundError | RateLimitedError>

  readonly downloadContent: (
    driveId: string,
    itemId: string,
  ) => Effect.Effect<Stream.Stream<Uint8Array, RateLimitedError>, ResourceNotFoundError>

  readonly uploadSmall: (
    driveId: string,
    parentPath: string,
    fileName: string,
    content: Uint8Array,
    contentType: string,
  ) => Effect.Effect<DriveItem, QuotaExceededError | RateLimitedError>

  readonly uploadSession: (
    driveId: string,
    parentPath: string,
    fileName: string,
    content: Stream.Stream<Uint8Array>,
    fileSize: number,
  ) => Effect.Effect<DriveItem, QuotaExceededError | RateLimitedError>

  readonly createFolder: (
    driveId: string,
    parentId: string,
    name: string,
  ) => Effect.Effect<DriveItem, RateLimitedError | InvalidRequestError>

  readonly delete: (
    driveId: string,
    itemId: string,
  ) => Effect.Effect<void, ResourceNotFoundError | RateLimitedError>

  readonly search: (
    driveId: string,
    query: string,
  ) => Effect.Effect<ODataPageType<DriveItem>, RateLimitedError>

  readonly createSharingLink: (
    driveId: string,
    itemId: string,
    type: "view" | "edit",
    scope: "anonymous" | "organization",
  ) => Effect.Effect<SharingLink, ResourceNotFoundError | RateLimitedError>
}

export const DriveService = Context.GenericTag<DriveService>("MsGraph/DriveService")
