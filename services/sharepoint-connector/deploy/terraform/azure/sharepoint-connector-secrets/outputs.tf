output "certificate" {
  description = "The PEM-encoded TLS certificate (public part). Null if certificate generation is disabled."
  value = var.tls_certificate != null ? {
    pem               = tls_self_signed_cert.certificate[0].cert_pem
    validity_end_time = formatdate("YYYY-MM-DD'T'hh:mm:ss'Z'", tls_self_signed_cert.certificate[0].validity_end_time)
    thumbprint_sha1   = upper(tls_self_signed_cert.certificate[0].cert_sha1)
    thumbprint_sha256 = upper(tls_self_signed_cert.certificate[0].cert_sha256)
  } : null
}

