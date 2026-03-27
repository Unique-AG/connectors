export type UserPermissions = "User.Read" | "User.Read.All" | "User.ReadWrite.All"

export type MailPermissions = "Mail.Read" | "Mail.ReadWrite" | "Mail.Send"

export type CalendarPermissions = "Calendars.Read" | "Calendars.ReadWrite"

export type DrivePermissions =
  | "Files.Read"
  | "Files.Read.All"
  | "Files.ReadWrite"
  | "Files.ReadWrite.All"

export type TeamsPermissions =
  | "Team.ReadBasic.All"
  | "Channel.ReadBasic.All"
  | "ChannelMessage.Send"

export type GroupPermissions = "Group.Read.All" | "Group.ReadWrite.All"

export type PlannerPermissions = "Tasks.Read" | "Tasks.ReadWrite"

export type AllDelegatedPermissions =
  | MailPermissions
  | CalendarPermissions
  | DrivePermissions
  | PlannerPermissions

export type AllApplicationPermissions =
  | UserPermissions
  | GroupPermissions
  | DrivePermissions
  | TeamsPermissions
