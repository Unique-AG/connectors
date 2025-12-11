# Connectors Monorepo

A monorepo containing Model Context Protocol (MCP) servers, Unique ingestion connectors and shared packages.

## Artifacts

Artifacts are identically available from two registries:

| Registry | Access |
|----------|--------|
| `ghcr.io/unique-ag/connectors/services/<service>` | Public, _here_ |
| `uniquecr.azurecr.io/connectors/services/<service>` | Authenticated clients with active _Master Service Agreements_ |

The ACR mirror is offered for convenience — source code remains disclosed in this repository. Connectors are out-of-tree components and not part of the core Unique platform.

For signature verification and SBOM extraction, see [`SECURITY.md`](./SECURITY.md#signed-artifacts).

## Develop Connectors
In [`DEVELOP.md`](./DEVELOP.md) developers find guides and documentation how to develop connectors in this repository.

## License

Refer to [`LICENSE.md`](./LICENSE.md).

## Security

Refer to [`SECURITY.md`](./SECURITY.md).
