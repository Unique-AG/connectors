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

resource "azurerm_key_vault_certificate" "entra_certificate_0" {
  count        = var.entra_application_certificate_0 != null ? 1 : 0
  name         = try(var.entra_application_certificate_0.name, "spc-entra-app-certificate-0")
  key_vault_id = var.entra_application_certificate_0 != null && var.entra_application_certificate_0.key_vault_id != null ? var.entra_application_certificate_0.key_vault_id : var.key_vault_id

  certificate_policy {
    issuer_parameters {
      name = "Self"
    }

    key_properties {
      exportable = true
      key_size   = 2048
      key_type   = "RSA"
      reuse_key  = true
    }

    lifetime_action {
      action {
        action_type = "AutoRenew"
      }

      trigger {
        days_before_expiry = 30
      }
    }

    secret_properties {
      content_type = "application/x-pkcs12"
    }

    x509_certificate_properties {
      extended_key_usage = ["1.3.6.1.5.5.7.3.2"]

      key_usage = [
        "dataEncipherment",
        "digitalSignature",
        "keyCertSign",
        "keyEncipherment",
      ]

      subject            = "CN=${try(var.entra_application_certificate_0.common_name, "spc-entra-app-certificate-0")}"
      validity_in_months = try(var.entra_application_certificate_0.validity_in_months, 12)
    }
  }
}
