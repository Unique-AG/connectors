import { Layer } from "effect"
import { ApplicationAuthLive } from "./Auth/ApplicationAuthLive"
import { DelegatedAuthLive } from "./Auth/DelegatedAuthLive"
import { ManagedIdentityAuthLive } from "./Auth/ManagedIdentityAuthLive"
import { OnBehalfOfAuthLive } from "./Auth/OnBehalfOfAuthLive"
import { MsGraphHttpClientLive } from "./Http/MsGraphHttpClientLive"
import { CalendarServiceLive } from "./Calendar/CalendarServiceLive"
import { DriveServiceLive } from "./Drive/DriveServiceLive"
import { GroupsServiceLive } from "./Groups/GroupsServiceLive"
import { MailServiceLive } from "./Mail/MailServiceLive"
import { PlannerServiceLive } from "./Planner/PlannerServiceLive"
import { TeamsServiceLive } from "./Teams/TeamsServiceLive"
import { UsersServiceLive } from "./Users/UsersServiceLive"
import type {
  AllApplicationPermissions,
  AllDelegatedPermissions,
  CalendarPermissions,
  DrivePermissions,
  GroupPermissions,
  MailPermissions,
  UserPermissions,
} from "./Auth/Permissions"

const delegatedHttpLive = MsGraphHttpClientLive<
  "Delegated",
  AllDelegatedPermissions
>("Delegated")

const applicationHttpLive = MsGraphHttpClientLive<
  "Application",
  AllApplicationPermissions
>("Application")

export const MsGraphDelegatedClientLive = Layer.mergeAll(
  MailServiceLive,
  CalendarServiceLive,
  DriveServiceLive,
  TeamsServiceLive,
  PlannerServiceLive,
).pipe(
  Layer.provide(delegatedHttpLive),
  Layer.provide(DelegatedAuthLive<AllDelegatedPermissions>()),
)

export const MsGraphApplicationClientLive = Layer.mergeAll(
  UsersServiceLive,
  GroupsServiceLive,
  DriveServiceLive,
  TeamsServiceLive,
).pipe(
  Layer.provide(applicationHttpLive),
  Layer.provide(ApplicationAuthLive<AllApplicationPermissions>()),
)

export const MsGraphOnBehalfOfClientLive = Layer.mergeAll(
  MailServiceLive,
  CalendarServiceLive,
  DriveServiceLive,
).pipe(
  Layer.provide(
    MsGraphHttpClientLive<"Delegated", MailPermissions | CalendarPermissions | DrivePermissions>("Delegated"),
  ),
  Layer.provide(
    OnBehalfOfAuthLive<MailPermissions | CalendarPermissions | DrivePermissions>(),
  ),
)

export const MsGraphManagedIdentityClientLive = Layer.mergeAll(
  UsersServiceLive,
  GroupsServiceLive,
).pipe(
  Layer.provide(
    MsGraphHttpClientLive<"Application", UserPermissions | GroupPermissions>("Application"),
  ),
  Layer.provide(
    ManagedIdentityAuthLive<UserPermissions | GroupPermissions>(),
  ),
)
