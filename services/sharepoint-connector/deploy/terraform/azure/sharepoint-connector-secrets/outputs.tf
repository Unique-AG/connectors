# https://registry.terraform.io/providers/hashicorp/azuread/latest/docs/resources/application_certificate#using-a-certificate-from-azure-key-vault
output "entra_certificate_0" { # rotation is not yet added but 0 is already put for later addition of entra_certificate_1
  description = "The Entra certificate for the SharePoint connector. Values must be passed to an Entra Application (Certificate Secret) or azuread_application_certificate."
  value = var.entra_application_certificate_0 != null ? {
    certificate = azurerm_key_vault_certificate.entra_certificate_0[0].certificate_data
    end_date    = azurerm_key_vault_certificate.entra_certificate_0[0].certificate_attribute[0].expires
    start_date  = azurerm_key_vault_certificate.entra_certificate_0[0].certificate_attribute[0].not_before
  } : null
}
