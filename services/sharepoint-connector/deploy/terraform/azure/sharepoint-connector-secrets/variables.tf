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
    # Until clarified how we handle certificate auto-renewal and secure storage and usage, users must supply the private key manually.
    # The key is a file and must be put into the KV with the CLI: az keyvault secret set --name manual-spc-certificate-private-key --vault-name <vault> -f <private-key.pem> --expires <Expiration UTC datetime (Y-m-d'T'H:M:S'Z')>
    spc-certificate-private-key = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
  }
}
