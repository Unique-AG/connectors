locals {
  cert_pem = var.tls_certificate != null ? tls_self_signed_cert.certificate[0].cert_pem : null
  # Extract base64 content from PEM, decode to DER, then compute hash (Azure thumbprint format)
  cert_der = local.cert_pem != null ? base64decode(
    replace(regex("-----BEGIN CERTIFICATE-----([\\s\\S]*)-----END CERTIFICATE-----", local.cert_pem)[0], "\n", "")
  ) : null
}

output "certificate" {
  description = "The PEM-encoded TLS certificate (public part). Null if certificate generation is disabled."
  value = var.tls_certificate != null ? {
    pem               = local.cert_pem
    validity_end_time = formatdate("YYYY-MM-DD'T'hh:mm:ss'Z'", tls_self_signed_cert.certificate[0].validity_end_time)
    thumbprint_sha1   = upper(sha1(local.cert_der))
    thumbprint_sha256 = upper(sha256(local.cert_der))
  } : null
}

