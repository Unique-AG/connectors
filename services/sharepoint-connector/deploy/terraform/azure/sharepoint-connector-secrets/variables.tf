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

variable "entra_application_certificate_0" {
  description = "Whether to create an Entra certificate for the SharePoint connector. Null disables the creation. If no key vault id is provided, the certificate will be created in the key_vault_id key vault."
  type = object({
    name               = optional(string)
    key_vault_id       = optional(string)
    common_name        = optional(string)
    organization       = optional(string)
    validity_in_months = optional(number)
    version            = optional(number)
  })
  default = {
    name               = "spc-entra-app-certificate-0"
    common_name        = "spc-entra-app-certificate-0"
    organization       = "Unique AI"
    validity_in_months = 12
    version            = 1 # TODO: Current rotation leads to downtime, two certificates are needed for a seamless rotation (rotate unused, add to app, move workload, rotate unused)
  }
}
