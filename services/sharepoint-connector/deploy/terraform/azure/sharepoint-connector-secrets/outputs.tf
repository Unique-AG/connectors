# https://registry.terraform.io/providers/hashicorp/azuread/latest/docs/resources/application_certificate
output "entra_certificate_0" {
  description = "The Entra certificate for the SharePoint connector. Values must be passed to an Entra Application (Certificate Secret) or azuread_application_certificate."
  value = var.entra_application_certificate_0 != null ? {
    certificate_pem = tls_self_signed_cert.entra_certificate_0[0].cert_pem
    private_key_pem = tls_private_key.entra_certificate_0[0].private_key_pem
    end_date        = tls_self_signed_cert.entra_certificate_0[0].validity_end_time
    start_date      = tls_self_signed_cert.entra_certificate_0[0].validity_start_time
    name            = try(var.entra_application_certificate_0.name, "spc-entra-app-certificate-0")
    version         = try(var.entra_application_certificate_0.version, 0)
    rotation_id     = random_id.certificate_rotation[0].hex
  } : null
}

output "certificate_rotation_version" {
  description = "Current version of the certificate for rotation tracking."
  value       = var.entra_application_certificate_0 != null ? try(var.entra_application_certificate_0.version, 0) : null
}
