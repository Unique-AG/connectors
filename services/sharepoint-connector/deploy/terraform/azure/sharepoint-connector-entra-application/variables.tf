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

variable "service_principal_configuration_enabled" {
  description = "Whether to configure a service principal for the Azure AD application. Might get disabled in certain cross-tenant scenarios where the counter-tenant creates the service principal."
  default     = true
  type        = bool
}

variable "sync_mode_role_preset" {
  description = "The sync mode preset to assign roles to the application. Valid values are 'content-only' or 'content-and-permissions'."
  type        = string
  default     = "content-only"
  validation {
    condition     = contains(["content-only", "content-and-permissions"], var.sync_mode_role_preset)
    error_message = "Invalid sync mode preset. Valid values are 'content-only' or 'content-and-permissions'."
  }
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
  #  "my-first-kuberentes-cluster" = {
  #  issuer      = "https://switzerlandnorth.oic.prod-aks.azure.com/<my_entra_tenant_id>/<my_aks_cluster_guid>/"
  #  subject     = "system:serviceaccount:<namespace>:<serviceaccount-name>"
  # }
}

variable "certificates" {
  description = "A map of Entra application certificates for the Azure AD application. Each key is the display name and the value contains the certificate configuration."
  type = map(object({
    certificate = string
    end_date    = string
    start_date  = string
  }))
  default = {}
}
