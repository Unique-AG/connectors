# https://registry.terraform.io/providers/hashicorp/azuread/latest/docs/resources/application_certificate
output "entra_certificate_0" { # rotation is not yet added but 0 is already put for later addition of entra_certificate_1
  description = "The Entra certificate for the SharePoint connector. Values must be passed to an Entra Application (Certificate Secret) or azuread_application_certificate."
  value = var.entra_application_certificate_0 != null ? {
    certificate_pem = tls_self_signed_cert.entra_certificate_0[0].cert_pem
    end_date        = tls_self_signed_cert.entra_certificate_0[0].validity_end_time
    start_date      = tls_self_signed_cert.entra_certificate_0[0].validity_start_time
  } : null
}
