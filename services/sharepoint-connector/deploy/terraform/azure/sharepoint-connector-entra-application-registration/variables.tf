variable "display_name" {
  description = "The display name for the Azure AD application registration."
  type        = string
  default     = "Unique AI SharePoint Connector"
}

variable "sign_in_audience" {
  description = "The Microsoft identity platform audiences that are supported by this application. Valid values are 'AzureADMyOrg', 'AzureADMultipleOrgs', 'AzureADandPersonalMicrosoftAccount', or 'PersonalMicrosoftAccount'. We default to AzureADMultipleOrgs as it's the most common use case. Stricter setups can revert back to 'AzureADMyOrg'."
  type        = string
  default     = "AzureADMultipleOrgs"
}

variable "roles_mode" {
  description = "The mode to assign roles to the application. Valid values are 'content-only' or 'permissions'."
  type        = string
  default     = "content-only"
  validation {
    condition     = contains(["content-only", "permissions"], var.roles_mode)
    error_message = "Invalid roles mode. Valid values are 'content-only' or 'permissions'."
  }
}

// TODO: Ask Dominik - if we have roles mode and these permissions should be tailored to our app,
// shouldn't these permissions be declared in locals block in main.tf based on roles_mode?
variable "graph_roles_content" {
  description = "A list of Graph API roles to assign to the application."
  type        = list(string)
  default     = ["Files.Read.All", "Sites.Selected"]
}

variable "graph_roles_permissions" {
  description = "A list of Graph API roles to assign to the application for permissions sync."
  type        = list(string)
  default     = ["Group.Read.All", "GroupMember.Read.All", "User.ReadBasic.All"]
}

variable "sharepoint_roles_permissions" {
  description = "A list of SharePoint API roles to assign to the application for permissions sync."
  type        = list(string)
  default     = ["Sites.Selected"]
}

variable "federated_identity_credentials" {
  description = "A map of federated identity credentials for the Azure AD application. Each key is the display name and the value contains the credential configuration. Currently we only support OIDC from this module. You can reuse the same application for multiple origins without sharing secrets by adding multiple issuers and subjects to the map."
  type = map(object({
    description = optional(string)
    audiences   = optional(list(string), ["api://AzureADTokenExchange"])
    issuer      = string
    subject     = string
  }))
  # Example
  # {
  #  "my-first-kuberentes-cluster" = {
  #  issuer      = "https://switzerlandnorth.oic.prod-aks.azure.com/<my_entra_tenant_id>/<my_aks_cluster_guid>/"
  #  subject     = "system:serviceaccount:<namespace>:<serviceaccount-name>"
  # }
}
