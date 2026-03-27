import { Schema } from "effect";

export const UserSchema = Schema.Struct({
  id: Schema.String,
  displayName: Schema.String,
  mail: Schema.NullOr(Schema.String),
  userPrincipalName: Schema.String,
  givenName: Schema.NullOr(Schema.String),
  surname: Schema.NullOr(Schema.String),
  jobTitle: Schema.NullOr(Schema.String),
  officeLocation: Schema.NullOr(Schema.String),
  mobilePhone: Schema.NullOr(Schema.String),
  businessPhones: Schema.Array(Schema.String),
  department: Schema.optional(Schema.NullOr(Schema.String)),
  employeeId: Schema.optional(Schema.NullOr(Schema.String)),
  preferredLanguage: Schema.optional(Schema.NullOr(Schema.String)),
  accountEnabled: Schema.optional(Schema.NullOr(Schema.Boolean)),
  usageLocation: Schema.optional(Schema.NullOr(Schema.String)),
  companyName: Schema.optional(Schema.NullOr(Schema.String)),
  city: Schema.optional(Schema.NullOr(Schema.String)),
  country: Schema.optional(Schema.NullOr(Schema.String)),
  streetAddress: Schema.optional(Schema.NullOr(Schema.String)),
  postalCode: Schema.optional(Schema.NullOr(Schema.String)),
  state: Schema.optional(Schema.NullOr(Schema.String)),
  createdDateTime: Schema.optional(Schema.NullOr(Schema.String)),
  lastPasswordChangeDateTime: Schema.optional(Schema.NullOr(Schema.String)),
  onPremisesSamAccountName: Schema.optional(Schema.NullOr(Schema.String)),
  onPremisesUserPrincipalName: Schema.optional(Schema.NullOr(Schema.String)),
  onPremisesSyncEnabled: Schema.optional(Schema.NullOr(Schema.Boolean)),
  assignedLicenses: Schema.optional(
    Schema.Array(
      Schema.Struct({
        skuId: Schema.String,
        disabledPlans: Schema.Array(Schema.String),
      }),
    ),
  ),
  proxyAddresses: Schema.optional(Schema.Array(Schema.String)),
});

export type User = Schema.Schema.Type<typeof UserSchema>;
