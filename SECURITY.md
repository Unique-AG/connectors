# Security Policy

## Reporting a Vulnerability

> [!TIP]
> If you'd wish to disclose a vulerability securely to Unique AI, you are welcome to send it to <a href="mailto:security@unique.ch"><code>security📧unique.ch</code></a> as well 💙

We have enabled the ability to privately report security issues through the Security tab above.

[Here are the details on how to file](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability#privately-reporting-a-security-vulnerability) a private vulnerability report.

A repository owner/maintainer will respond as fast as possible to coordinate confirmation of issue and remediation.

Thank you for helping to ensure this code stays secure.

## Signed artifacts

All container images are signed using [Sigstore Cosign](https://docs.sigstore.dev/cosign/overview/) with keyless signing via GitHub OIDC. Images also include SBOM and provenance attestations.

### Verifying image signatures

Install [cosign](https://docs.sigstore.dev/cosign/system_config/installation/) and run:

```bash
cosign verify ghcr.io/unique-ag/connectors/services/<service-name>:<version> \
  --certificate-identity-regexp="^https://github.com/unique-ag/connectors/\.github/workflows/.*@refs/heads/main$" \
  --certificate-oidc-issuer=https://token.actions.githubusercontent.com
```

This verifies the image was built and signed by our official CI/CD pipeline on the `main` branch.

We use `--certificate-identity-regexp` instead of an exact match because multiple service-specific workflows invoke our shared CD template. This remains secure because the pattern is scoped to `unique-ag/connectors` — a repository we exclusively control — and only accepts signatures from workflows on the `main` branch.

### Verifying provenance attestation

```bash
cosign verify-attestation ghcr.io/unique-ag/connectors/services/<service-name>:<version> \
  --type=slsaprovenance \
  --certificate-identity-regexp="^https://github.com/unique-ag/connectors/\.github/workflows/.*@refs/heads/main$" \
  --certificate-oidc-issuer=https://token.actions.githubusercontent.com
```

### Extracting the SBOM

```bash
cosign download sbom ghcr.io/unique-ag/connectors/services/<service-name>:<version> > sbom.spdx.json
```

The SBOM is in SPDX format and lists all packages included in the image.

### On the private `uniquecr.azurecr.io` registry

Azure ACR uses the OCI 1.1 Referrers API, so signatures are linked as referrers rather than stored as separate `.sig` tags (as seen on GHCR). Verification with `cosign verify` works identically — it discovers signatures automatically via either method.

To inspect the full artifact tree (signatures, attestations, SBOMs):

```bash
cosign tree uniquecr.azurecr.io/connectors/services/<service-name>:<version>
```