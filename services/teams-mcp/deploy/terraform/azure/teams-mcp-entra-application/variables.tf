variable "display_name" {
  description = "The display name for the Azure AD application registration."
  type        = string
  default     = "Unique AI Teams MCP"
}

variable "notes" {
  description = "Notes for the Azure AD application. These will be inherited by the service principal if not explicitly overridden."
  type        = string
  default     = null
}

variable "sign_in_audience" {
  description = "The Microsoft identity platform audiences that are supported by this application. Valid values are 'AzureADMyOrg', 'AzureADMultipleOrgs', 'AzureADandPersonalMicrosoftAccount', or 'PersonalMicrosoftAccount'. We default to AzureADMultipleOrgs as it's the most common use case. Stricter setups can revert back to 'AzureADMyOrg'."
  type        = string
  default     = "AzureADMultipleOrgs"
}

variable "service_principal_configuration" {
  description = "Configuration for the service principal. Set to null to skip service principal creation (useful in cross-tenant scenarios). When set, you can provide optional tags and notes that override the application-level values."
  type = object({
    tags  = optional(list(string))
    notes = optional(string)
  })
  default = {}
}

variable "redirect_uris" {
  description = "List of OAuth redirect URIs for the application. Should include the callback URL for your Teams MCP server."
  type        = list(string)
  default     = []
}

variable "federated_identity_credentials" {
  description = "A map of federated identity credentials for the Azure AD application. Each key is the display name and the value contains the credential configuration. Currently we only support OIDC from this module. You can reuse the same application for multiple origins without sharing secrets by adding multiple issuers and subjects to the map."
  type = map(object({
    description = optional(string)
    audiences   = optional(list(string), ["api://AzureADTokenExchange"])
    issuer      = string
    subject     = string
  }))
  default = {}
  # Example
  # {
  #  "my-first-kubernetes-cluster" = {
  #  issuer      = "https://switzerlandnorth.oic.prod-aks.azure.com/<my_entra_tenant_id>/<my_aks_cluster_guid>/"
  #  subject     = "system:serviceaccount:<namespace>:<serviceaccount-name>"
  # }
}

variable "create_client_secret" {
  description = "Whether to create a client secret for the application. Set to false if you only want to use federated credentials (workload identity)."
  type        = bool
  default     = false
}

variable "client_secret_end_date" {
  description = "The end date for the client secret. Defaults to approximately 2 years from creation."
  type        = string
  default     = null
}
