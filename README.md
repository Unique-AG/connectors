# Connectors Monorepo

A monorepo containing Model Context Protocol (MCP) servers, Unique ingestion connectors and shared packages.

## Artifacts

Artifacts are identically available from two registries:

| Artifact | Registry | Access |
|----------|----------|--------|
| Container Images | `ghcr.io/unique-ag/connectors/services/<service>` | Public, _here_ |
| Container Images | `uniquecr.azurecr.io/connectors/services/<service>` | Authenticated clients with active _Master Service Agreements_ |
| Helm Charts | `oci://ghcr.io/unique-ag/connectors/helm/<service>` | Public, _here_ |
| Helm Charts | `oci://uniquecr.azurecr.io/connectors/helm/<service>` | Authenticated clients with active _Master Service Agreements_ |

The ACR mirror is offered for convenience — source code remains disclosed in this repository. Connectors are out-of-tree components and not part of the core Unique platform.

For container image signature verification and SBOM extraction, see [`SECURITY.md`](./SECURITY.md#signed-artifacts).

> [!NOTE]
> Authenticating against Helm registries is less common than authenticating against image registries, and it happens at a different point in the lifecycle (during deployment). If you're new to Helm registry authentication, we recommend starting with the public registry. The private registry is available for teams that have experience with Helm authentication and can manage the additional setup.

## Develop Connectors
In [`DEVELOP.md`](./DEVELOP.md) developers find guides and documentation how to develop connectors in this repository.

## License

Refer to [`LICENSE.md`](./LICENSE.md).

## Security

Refer to [`SECURITY.md`](./SECURITY.md).
