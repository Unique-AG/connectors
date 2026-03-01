variable "display_name" {
  description = "The display name for the Azure AD application registration."
  type        = string
  default     = "Unique AI Outlook Semantic MCP"
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
  description = "List of OAuth redirect URIs for the application. Should include the callback URL for your Outlook Semantic MCP server."
  type        = list(string)
  default     = []
}

variable "client_secrets_prefix" {
  description = "The prefix for the client secrets. This will be prepended to the client secret name but omitted if a secrets.explicit_name is provided."
  type        = string
  default     = "outlook-semantic-mcp"
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
    The end date is mandatory on purpose to foster outlook awareness of secret rotation and expiration.
  EOT
  type = map(object({
    client_secret = object({
      explicit_name    = optional(string)
      key_vault_id     = string
      rotation_counter = optional(number, 0)
      end_date         = string
    })
  }))
  default = {}

  validation {
    condition = alltrue([
      for k, v in var.confidential_clients :
      can(regex("^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}Z$", v.client_secret.end_date))
    ])
    error_message = "The end_date must be in RFC3339 format (e.g. 2018-01-01T01:02:03Z)."
  }
}

variable "service_principal_configuration" {
  description = <<-EOT
    Configuration for the service principal. Set to null to skip service principal creation
    (useful in cross-tenant scenarios where the customer tenant manages the service principal).
    When set (even to {}), creates a service principal and grants admin consent for all
    Microsoft Graph delegated scopes on behalf of all users in the tenant.
    For multi-tenant apps, each customer tenant admin must grant consent separately
    (via the admin consent URL or interactive flow).
  EOT
  type = object({
    notes = optional(string)
  })
  default = {}
}
