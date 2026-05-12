variable "key_vault_id" {
  description = "The ID of the key vault, all created secrets will be placed here."
  type        = string
}

variable "secrets_placeholders" {
  description = "Map of manual secrets created in the key vault. The 'manual-' prefix is prepended automatically. Operator pastes the actual value into each slot post-apply."
  type = map(object({
    create          = optional(bool, true)
    expiration_date = optional(string, "2099-12-31T23:59:59Z")
  }))
  default = {
    # Kyckr REST API Bearer token (KYCKR_API_KEY). Issued by Kyckr.
    kyckr-api-key = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
    # Shared secret protecting the /mcp endpoint (MCP_API_KEY).
    # Generate once with: openssl rand -hex 32
    kyckr-mcp-key = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
  }
}
