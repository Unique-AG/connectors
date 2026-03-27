import { Schema } from "effect";

export const AssignedLicenseSchema = Schema.Struct({
  skuId: Schema.String,
  disabledPlans: Schema.Array(Schema.String),
});

export type AssignedLicense = Schema.Schema.Type<typeof AssignedLicenseSchema>;

export const GroupSchema = Schema.Struct({
  id: Schema.String,
  displayName: Schema.String,
  description: Schema.NullOr(Schema.String),
  mail: Schema.NullOr(Schema.String),
  mailEnabled: Schema.Boolean,
  mailNickname: Schema.String,
  securityEnabled: Schema.Boolean,
  groupTypes: Schema.Array(Schema.String),
  membershipRule: Schema.optional(Schema.NullOr(Schema.String)),
  membershipRuleProcessingState: Schema.optional(
    Schema.NullOr(Schema.Literal("On", "Paused")),
  ),
  createdDateTime: Schema.optional(Schema.NullOr(Schema.String)),
  deletedDateTime: Schema.optional(Schema.NullOr(Schema.String)),
  renewedDateTime: Schema.optional(Schema.NullOr(Schema.String)),
  expirationDateTime: Schema.optional(Schema.NullOr(Schema.String)),
  classification: Schema.optional(Schema.NullOr(Schema.String)),
  preferredDataLocation: Schema.optional(Schema.NullOr(Schema.String)),
  preferredLanguage: Schema.optional(Schema.NullOr(Schema.String)),
  theme: Schema.optional(Schema.NullOr(Schema.String)),
  visibility: Schema.optional(Schema.NullOr(Schema.Literal("Private", "Public", "HiddenMembership"))),
  isAssignableToRole: Schema.optional(Schema.NullOr(Schema.Boolean)),
  isManagementRestricted: Schema.optional(Schema.NullOr(Schema.Boolean)),
  securityIdentifier: Schema.optional(Schema.NullOr(Schema.String)),
  onPremisesDomainName: Schema.optional(Schema.NullOr(Schema.String)),
  onPremisesNetBiosName: Schema.optional(Schema.NullOr(Schema.String)),
  onPremisesSamAccountName: Schema.optional(Schema.NullOr(Schema.String)),
  onPremisesSecurityIdentifier: Schema.optional(Schema.NullOr(Schema.String)),
  onPremisesSyncEnabled: Schema.optional(Schema.NullOr(Schema.Boolean)),
  onPremisesLastSyncDateTime: Schema.optional(Schema.NullOr(Schema.String)),
  proxyAddresses: Schema.optional(Schema.Array(Schema.String)),
  assignedLabels: Schema.optional(
    Schema.Array(
      Schema.Struct({
        labelId: Schema.optional(Schema.String),
        displayName: Schema.optional(Schema.String),
      }),
    ),
  ),
  assignedLicenses: Schema.optional(Schema.Array(AssignedLicenseSchema)),
  licenseProcessingState: Schema.optional(
    Schema.NullOr(
      Schema.Struct({
        state: Schema.optional(Schema.String),
      }),
    ),
  ),
  resourceProvisioningOptions: Schema.optional(Schema.Array(Schema.String)),
  teamId: Schema.optional(Schema.NullOr(Schema.String)),
  hasMembersWithLicenseErrors: Schema.optional(Schema.NullOr(Schema.Boolean)),
  allowExternalSenders: Schema.optional(Schema.NullOr(Schema.Boolean)),
  autoSubscribeNewMembers: Schema.optional(Schema.NullOr(Schema.Boolean)),
  hideFromAddressLists: Schema.optional(Schema.NullOr(Schema.Boolean)),
  hideFromOutlookClients: Schema.optional(Schema.NullOr(Schema.Boolean)),
  isSubscribedByMail: Schema.optional(Schema.NullOr(Schema.Boolean)),
  unseenCount: Schema.optional(Schema.NullOr(Schema.Number)),
});

export type Group = Schema.Schema.Type<typeof GroupSchema>;

export const CreateGroupPayloadSchema = Schema.Struct({
  displayName: Schema.String,
  mailEnabled: Schema.Boolean,
  mailNickname: Schema.String,
  securityEnabled: Schema.Boolean,
  description: Schema.optional(Schema.String),
  groupTypes: Schema.optional(Schema.Array(Schema.String)),
  visibility: Schema.optional(Schema.Literal("Private", "Public", "HiddenMembership")),
  members: Schema.optional(Schema.Array(Schema.String)),
  owners: Schema.optional(Schema.Array(Schema.String)),
});

export type CreateGroupPayload = Schema.Schema.Type<typeof CreateGroupPayloadSchema>;
