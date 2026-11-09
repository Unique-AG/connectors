variable "key_vault_id" {
  description = "The ID of the key vault, all created secrets will be placed here."
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
      The LSEG client credentials the MCP exchanges for a bearer token (.env.example):
      - world-check-mcp-upstream-api-key: the service-account id (UPSTREAM_API_KEY)
      - world-check-mcp-upstream-api-secret: that account's password (UPSTREAM_API_SECRET)
    */
    world-check-mcp-upstream-api-key    = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
    world-check-mcp-upstream-api-secret = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
  }
}
