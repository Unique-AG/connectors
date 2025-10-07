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
      The Zitadel Client ID is on purpose not terraformed. Explicit code definition is more maintainable and easier to debug and change.
      Users preferring to manage the Zitadel Client ID via terraform can still do so by superseding this variables default.
    */
    spc-zitadel-client-secret = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
  }
}
