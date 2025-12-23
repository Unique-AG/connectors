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

variable "redirect_uris" {
  description = "List of OAuth redirect URIs for the application. Should include the callback URL for your Teams MCP server."
  type        = list(string)
  default     = []
}

variable "create_client_secret" {
  description = "Whether to create a client secret for the application."
  type        = bool
  default     = true
}

variable "client_secret_end_date" {
  description = "The end date for the client secret. Defaults to approximately 2 years from creation."
  type        = string
  default     = null
}
