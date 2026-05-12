variable "key_vault_id" {
  description = "The ID of the key vault, all created secrets will be placed here."
  type        = string
}

variable "key_vault_sensitive_id" {
  description = "The ID of the sensitive key vault for auto-generated secrets. If set, takes precedence over key_vault_id for secrets_to_create. Pass null to use key_vault_id."
  type        = string
}

variable "secrets_placeholders" {
  description = "Map of secrets that are manually created and need to be placed in the core key vault. The manual- prefix is prepended automatically."
  type = map(object({
    create          = optional(bool, true)
    expiration_date = optional(string, "2099-12-31T23:59:59Z")
  }))
  default = {
    /**
      Manual secrets that need to be set based on Kyckr MCP configuration:

      Kyckr Configuration (kyckr.config.ts):
      - kyckr-mcp-api-key: The Kyckr API key sent as Bearer token to the Kyckr REST API (KYCKR_API_KEY)
    */
    kyckr-mcp-api-key = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
  }
}

variable "secrets_to_create" {
  description = "List of secrets that are automatically generated and should be placed in the sensitive key vault. Increment a counter to rotate the secret."
  type = map(object({
    content_type     = optional(string, "text/plain")
    create           = optional(bool, true)
    expiration_date  = optional(string, "2099-12-31T23:59:59Z")
    length           = optional(number)
    name             = optional(string)
    rotation_counter = optional(number, 0)
  }))
  default = {
    /**
      Auto-generated secrets (hex output from random_bytes):

      Secret format requirements (from src/config/app.config.ts):
      - MCP API Key: 64-char hex (openssl rand -hex 32) -> length=32
        Required shared secret protecting the /mcp endpoint, passed as the `api-key` query parameter.
    */
    hex_mcp_api_key = { create = true, name = "kyckr-mcp-api-key", content_type = "text/hex", rotation_counter = 0, expiration_date = "2099-12-31T23:59:59Z" }
  }
}
