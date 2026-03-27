import { Schema } from "effect";

export const EmailAddressSchema = Schema.Struct({
  address: Schema.String,
  name: Schema.optional(Schema.String),
});

export type EmailAddress = Schema.Schema.Type<typeof EmailAddressSchema>;

export const RecipientSchema = Schema.Struct({
  emailAddress: EmailAddressSchema,
});

export type Recipient = Schema.Schema.Type<typeof RecipientSchema>;

export const IdentitySchema = Schema.Struct({
  displayName: Schema.NullOr(Schema.String),
  id: Schema.NullOr(Schema.String),
});

export type Identity = Schema.Schema.Type<typeof IdentitySchema>;

export const IdentitySetSchema = Schema.Struct({
  user: Schema.optional(IdentitySchema),
  application: Schema.optional(IdentitySchema),
  device: Schema.optional(IdentitySchema),
});

export type IdentitySet = Schema.Schema.Type<typeof IdentitySetSchema>;

export const DateTimeTimeZoneSchema = Schema.Struct({
  dateTime: Schema.String,
  timeZone: Schema.String,
});

export type DateTimeTimeZone = Schema.Schema.Type<typeof DateTimeTimeZoneSchema>;
