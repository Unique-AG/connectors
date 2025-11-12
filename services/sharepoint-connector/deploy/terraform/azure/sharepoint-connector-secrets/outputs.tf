output "certificate" {
  description = "The PEM-encoded TLS certificate (public part). Null if certificate generation is disabled."
  value = var.tls_certificate != null ? {
    pem             = tls_self_signed_cert.certificate[0].cert_pem
    expiration_date = tls_self_signed_cert.certificate[0].not_after
  } : null
}

