output "certificate_pem" {
  description = "The PEM-encoded TLS certificate (public part). Null if certificate generation is disabled."
  value       = var.tls_certificate != null ? tls_self_signed_cert.certificate[0].cert_pem : null
}

