variable "key_vault_id" {
  description = "The ID of the key vault, all created secrets will be placed here."
  type        = string
}

variable "secrets_placeholders" {
  description = "List of secrets that are manually created and need to be placed in the core key vault. The manual- prefix is prepended automatically."
  type = map(object({
    create          = optional(bool, true)
    expiration_date = optional(string, "2099-12-31T23:59:59Z")
  }))
  default = {
    factset-zitadel-client-secret = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
    factset-auth-config           = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
  }
}
