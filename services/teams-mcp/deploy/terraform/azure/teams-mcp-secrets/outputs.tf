output "manual_secrets" {
  description = "List of manual secret names that need to be populated."
  value       = [for k, v in var.secrets_placeholders : "manual-${k}" if v.create]
}
