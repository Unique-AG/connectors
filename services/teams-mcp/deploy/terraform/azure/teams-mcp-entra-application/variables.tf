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
  description = <<-EOT
    The Microsoft identity platform audiences that are supported by this application.
    Valid values are 'AzureADMyOrg' and 'AzureADMultipleOrgs'.
    We default to 'AzureADMultipleOrgs' as it's the most common use case.
    Stricter setups can revert back to 'AzureADMyOrg'.
  EOT
  type        = string
  default     = "AzureADMultipleOrgs"

  validation {
    condition     = contains(["AzureADMyOrg", "AzureADMultipleOrgs"], var.sign_in_audience)
    error_message = "The sign_in_audience must be one of: 'AzureADMyOrg', or 'AzureADMultipleOrgs'."
  }
}

variable "redirect_uris" {
  description = "List of OAuth redirect URIs for the application. Should include the callback URL for your Teams MCP server."
  type        = list(string)
  default     = []
}

variable "confidential_clients" {
  description = <<-EOT
    Map of confidential clients and their client secrets.
    The client secret will be stored in the key vault specified in the client_secret.key_vault_id.
    According to our [Design Principles](https://github.com/Unique-AG/terraform-modules/blob/main/DESIGN.md),
    the caller of the module is responsible for necessary permissions to the key vault (secrets).
    The module outputs secret_ids where upon which the caller can grant granular read permissions.
    It is strongly recommended to tie one secret to exactly one workload identity.
    Zero-downtime rotation is currently not supported, rotating the counter will result in a downtime as long as the
    affected workload does not pickup the new secret and gets eventually restarted.
  EOT
  type = map(object({
    client_secret = object({
      explicit_name    = optional(string)
      key_vault_id     = string
      rotation_counter = optional(number, 0)
      end_date         = optional(string)
    })
  }))
  default = {}

  validation {
    condition = alltrue([
      for k, v in var.confidential_clients :
      v.client_secret.end_date == null || can(regex("^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}Z$", v.client_secret.end_date))
    ])
    error_message = "The end_date must be in RFC3339 format (e.g. 2018-01-01T01:02:03Z)."
  }
}
