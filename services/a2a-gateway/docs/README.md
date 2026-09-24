# a2a-gateway — design

Optional connectors service that gives Unique bidirectional [A2A v1.0](https://a2a-protocol.org/v1.0.0/specification/) support:

- **Inbound**: external A2A clients call published native Unique spaces.
- **Outbound**: Unique users and agents call external A2A agents through *A2A External Agent* spaces (direct chat and sub-agent).

Linear: [KRA-11](https://linear.app/krauss/issue/KRA-11) (epic) · [KRA-18](https://linear.app/krauss/issue/KRA-18) (this design).

| Doc | Content |
| --- | --- |
| [architecture.md](./architecture.md) | Context, components, ownership boundaries |
| [contracts.md](./contracts.md) | Public A2A, management, internal and core-capability API surfaces |
| [identity-and-trust.md](./identity-and-trust.md) | Both identity flows, trust boundaries, threat review |
| [data-model.md](./data-model.md) | Persistence model (basis for KRA-20) |
| [flows.md](./flows.md) | Sequence diagrams for the main interactions |
| [compatibility-profile.md](./compatibility-profile.md) | Pinned protocol profile, SDK, content matrix, peer limitations |
| [decisions.md](./decisions.md) | Decision log and open questions |
| [implementation-plan.md](./implementation-plan.md) | Target layout, config, ticket mapping (KRA-19/20/21) |

Status: **draft for review** — nothing in this folder is implemented yet. Implementation starts with KRA-19.
