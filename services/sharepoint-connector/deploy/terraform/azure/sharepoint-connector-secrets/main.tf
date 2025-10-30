resource "azurerm_key_vault_secret" "manual_secret" {
  for_each        = var.secrets_placeholders
  content_type    = lookup(each.value, "content_type", "text/plain")
  expiration_date = lookup(each.value, "expiration_date", "2099-12-31T23:59:59Z")
  key_vault_id    = var.key_vault_id
  name            = "manual-${each.key}"
  value           = "<TO BE SET MANUALLY>"
  lifecycle {
    ignore_changes = [value, tags, content_type]
  }
}

# Private key for the certificate
ephemeral "tls_private_key" "entra_certificate_0" {
  count     = var.entra_application_certificate_0 != null ? 1 : 0
  algorithm = "RSA"
  rsa_bits  = 2048
}

# Self-signed certificate
resource "tls_self_signed_cert" "entra_certificate_0" {
  count           = var.entra_application_certificate_0 != null ? 1 : 0
  private_key_pem = tls_private_key.entra_certificate_0[0].private_key_pem

  subject {
    common_name  = var.entra_application_certificate_0.common_name
    organization = var.entra_application_certificate_0.organization
  }

  validity_period_hours = try(var.entra_application_certificate_0.validity_in_months, 12) * 30 * 24

  allowed_uses = [
    "digital_signature",
  ]
}

# Store the PEM certificate in Key Vault
resource "azurerm_key_vault_secret" "entra_certificate_pem" {
  count           = var.entra_application_certificate_0 != null ? 1 : 0
  name            = var.entra_application_certificate_0.name
  value           = tls_self_signed_cert.entra_certificate_0[0].cert_pem
  key_vault_id    = coalesce(var.entra_application_certificate_0.key_vault_id, var.key_vault_id)
  content_type    = "application/x-pem-file"
  expiration_date = tls_self_signed_cert.entra_certificate_0[0].validity_end_time
}

# Store the private key in Key Vault (needed for PFX export)
resource "azurerm_key_vault_secret" "entra_certificate_key" {
  count            = var.entra_application_certificate_0 != null ? 1 : 0
  name             = "${var.entra_application_certificate_0.name}-key"
  value_wo         = tls_private_key.entra_certificate_0[0].private_key_pem
  value_wo_version = var.entra_application_certificate_0.version
  key_vault_id     = coalesce(var.entra_application_certificate_0.key_vault_id, var.key_vault_id)
  content_type     = "application/x-pem-file"
  expiration_date  = tls_self_signed_cert.entra_certificate_0[0].validity_end_time
}
