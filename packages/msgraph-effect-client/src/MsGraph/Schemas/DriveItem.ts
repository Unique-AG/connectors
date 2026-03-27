import { Schema } from "effect";

import { IdentitySetSchema } from "./Common";

export const DriveItemSchema = Schema.Struct({
  id: Schema.String,
  name: Schema.String,
  size: Schema.Number,
  webUrl: Schema.String,
  createdDateTime: Schema.DateFromString,
  lastModifiedDateTime: Schema.DateFromString,
  createdBy: IdentitySetSchema,
  lastModifiedBy: IdentitySetSchema,
  description: Schema.optional(Schema.NullOr(Schema.String)),
  eTag: Schema.optional(Schema.String),
  cTag: Schema.optional(Schema.String),
  file: Schema.optional(
    Schema.Struct({
      mimeType: Schema.String,
      hashes: Schema.optional(
        Schema.Struct({
          sha1Hash: Schema.optional(Schema.String),
          sha256Hash: Schema.optional(Schema.String),
          quickXorHash: Schema.optional(Schema.String),
          crc32Hash: Schema.optional(Schema.String),
        }),
      ),
    }),
  ),
  folder: Schema.optional(
    Schema.Struct({
      childCount: Schema.Number,
      view: Schema.optional(
        Schema.Struct({
          viewType: Schema.optional(Schema.String),
          sortBy: Schema.optional(Schema.String),
          sortOrder: Schema.optional(Schema.String),
        }),
      ),
    }),
  ),
  parentReference: Schema.optional(
    Schema.Struct({
      driveId: Schema.String,
      driveType: Schema.optional(Schema.Literal("personal", "business", "documentLibrary")),
      id: Schema.String,
      name: Schema.optional(Schema.String),
      path: Schema.optional(Schema.String),
      siteId: Schema.optional(Schema.String),
    }),
  ),
  image: Schema.optional(
    Schema.Struct({
      width: Schema.optional(Schema.Number),
      height: Schema.optional(Schema.Number),
    }),
  ),
  photo: Schema.optional(
    Schema.Struct({
      takenDateTime: Schema.optional(Schema.String),
      cameraMake: Schema.optional(Schema.String),
      cameraModel: Schema.optional(Schema.String),
      fNumber: Schema.optional(Schema.Number),
      exposureDenominator: Schema.optional(Schema.Number),
      exposureNumerator: Schema.optional(Schema.Number),
      focalLength: Schema.optional(Schema.Number),
      iso: Schema.optional(Schema.Number),
    }),
  ),
  video: Schema.optional(
    Schema.Struct({
      duration: Schema.optional(Schema.Number),
      width: Schema.optional(Schema.Number),
      height: Schema.optional(Schema.Number),
      bitrate: Schema.optional(Schema.Number),
      frameRate: Schema.optional(Schema.Number),
    }),
  ),
  remoteItem: Schema.optional(
    Schema.Struct({
      id: Schema.String,
      name: Schema.optional(Schema.String),
      size: Schema.optional(Schema.Number),
      webUrl: Schema.optional(Schema.String),
    }),
  ),
  shared: Schema.optional(
    Schema.Struct({
      scope: Schema.optional(Schema.Literal("anonymous", "organization", "users")),
      owner: Schema.optional(IdentitySetSchema),
      sharedBy: Schema.optional(IdentitySetSchema),
      sharedDateTime: Schema.optional(Schema.String),
    }),
  ),
  deleted: Schema.optional(
    Schema.Struct({
      state: Schema.optional(Schema.String),
    }),
  ),
  malware: Schema.optional(Schema.Struct({})),
  package: Schema.optional(
    Schema.Struct({
      type: Schema.optional(Schema.String),
    }),
  ),
  root: Schema.optional(Schema.Struct({})),
  specialFolder: Schema.optional(
    Schema.Struct({
      name: Schema.String,
    }),
  ),
  webDavUrl: Schema.optional(Schema.String),
  downloadUrl: Schema.optional(Schema.String),
});

export type DriveItem = Schema.Schema.Type<typeof DriveItemSchema>;

export const UploadSessionSchema = Schema.Struct({
  uploadUrl: Schema.String,
  expirationDateTime: Schema.DateFromString,
  nextExpectedRanges: Schema.Array(Schema.String),
});

export type UploadSession = Schema.Schema.Type<typeof UploadSessionSchema>;

export const SharingLinkSchema = Schema.Struct({
  id: Schema.optional(Schema.String),
  type: Schema.Literal("view", "edit", "embed"),
  scope: Schema.Literal("anonymous", "organization", "users"),
  webUrl: Schema.String,
  webHtml: Schema.optional(Schema.String),
  application: Schema.optional(
    Schema.Struct({
      id: Schema.String,
      displayName: Schema.String,
    }),
  ),
  preventsDownload: Schema.optional(Schema.Boolean),
  expirationDateTime: Schema.optional(Schema.NullOr(Schema.String)),
});

export type SharingLink = Schema.Schema.Type<typeof SharingLinkSchema>;

export const SharingLinkResponseSchema = Schema.Struct({
  id: Schema.String,
  roles: Schema.Array(Schema.String),
  shareId: Schema.optional(Schema.String),
  expirationDateTime: Schema.optional(Schema.NullOr(Schema.String)),
  hasPassword: Schema.optional(Schema.Boolean),
  link: SharingLinkSchema,
});

export type SharingLinkResponse = Schema.Schema.Type<typeof SharingLinkResponseSchema>;
