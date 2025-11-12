resource "azurerm_key_vault_secret" "manual_secret" {
  for_each        = var.secrets_placeholders
  content_type    = lookup(each.value, "content_type", "text/plain")
  expiration_date = lookup(each.value, "expiration_date", "2099-12-31T23:59:59Z")
  key_vault_id    = var.key_vault_id
  name            = "manual-${each.key}"
  value           = "<TO BE SET MANUALLY>"
  lifecycle {
    ignore_changes = [value, tags, content_type, expiration_date]
  }
}

resource "terraform_data" "certificate_rotation" {
  count = var.tls_certificate != null ? 1 : 0
  input = var.tls_certificate.rotation_trigger
}

resource "tls_private_key" "private_key" {
  count     = var.tls_certificate != null ? 1 : 0
  algorithm = "RSA"
  rsa_bits  = 2048

  lifecycle {
    create_before_destroy = true
    replace_triggered_by = [
      terraform_data.certificate_rotation[0].output
    ]
  }
}

resource "tls_self_signed_cert" "certificate" {
  count           = var.tls_certificate != null ? 1 : 0
  private_key_pem = tls_private_key.private_key[0].private_key_pem
  subject {
    common_name = coalesce(var.tls_certificate.subject, "sharepoint-connector.unique.dev")
  }
  validity_period_hours = 24 * 30 * 20 # ~ 20 months # TODO: technically the rotation can trigger at this time, but someone would need to manually run terraform at that time and also pass the certificate output to the application
  allowed_uses          = ["digital_signature"]

  lifecycle {
    create_before_destroy = true
  }
}

resource "azurerm_key_vault_secret" "certificate_private_key" {
  count = var.tls_certificate != null ? 1 : 0

  content_type    = "application/x-pem-file"
  expiration_date = var.tls_certificate.expiration_date
  key_vault_id    = coalesce(var.tls_certificate.key_vault_id, var.key_vault_id)
  name            = var.tls_certificate.secret_name
  value           = tls_private_key.private_key[0].private_key_pem

  lifecycle {
    create_before_destroy = true
  }
}

