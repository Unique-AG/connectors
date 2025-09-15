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

variable "required_resource_access" {
  description = "A map of resource application IDs to their required access permissions. Each value should be a list of objects with 'id' (permission ID) and 'type' (permission type: 'Scope' or 'Role')"
  type = map(object({
    identifier = string
    means      = string # only added for modules internal documentation reference, thus required
    type       = optional(string, "Scope")
  }))
  # https://learn.microsoft.com/en-us/graph/permissions-reference
  default = {
    "Files.Read.All" = {
      # https://learn.microsoft.com/en-us/graph/permissions-reference#filesreadall
      means      = "Application"
      identifier = "01d4889c-1287-42c6-ac1f-5d1e02578ef6"
    }
    "Directory.Read.All" = {
      # https://learn.microsoft.com/en-us/graph/permissions-reference#directoryreadall
      means      = "Application"
      identifier = "7ab1d382-f21e-4acd-a863-ba3e13f7da61"
    }
    "Sites.Read.All" = {
      # TODO: @lorand93: reason this permission exceptionally well
      # https://learn.microsoft.com/en-us/graph/permissions-reference#sidesreadall
      means      = "Application"
      identifier = "332a536c-c7ef-4017-ab91-336970924f0d"
    }
    "User.Read.All" = {
      # TODO: @lorand93: reason this permission exceptionally well
      # https://learn.microsoft.com/en-us/graph/permissions-reference#userreadall
      means      = "Application"
      identifier = "df021288-bdef-4463-88db-98f22de89214"
    }
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
  # Example
  # {
  #  "my-first-kuberentes-cluster" = {
  #  issuer      = "https://switzerlandnorth.oic.prod-aks.azure.com/<my_entra_tenant_id>/<my_aks_cluster_guid>/"
  #  subject     = "system:serviceaccount:<namespace>:<serviceaccount-name>"
  # }
}
