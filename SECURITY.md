Please follow the [`Unique Security Policy v1`](https://github.com/Unique-AG/license/blob/main/security-policy/v1.md) 💙

## Temporary security workarounds

This table tracks measures that exist **only because an upstream fix does not exist yet**. Each one
must leave when its exit condition is true. Without this list they stay forever: a stale
`js-yaml` override once froze this repository on a vulnerable version and blocked two HIGH alerts
from closing.

Add a row in the same PR that adds the workaround. Delete the row in the PR that removes it.

| ID | Workaround | Exit condition, and how to check it | Added |
|---|---|---|---|
| SD-1 | `package.json` — pnpm override `multer@<2.4.0` | The catalog moves to `@nestjs/platform-express` >= 12.0.3. The whole 11.x line pins multer 2.2.0 and never patches it.<br>`npm view @nestjs/platform-express@<catalog version> dependencies.multer` | #1031 |
| SD-2 | `package.json` — pnpm override `uuid@<11.1.1` | `typeid-js` declares uuid >= 11.1.1, and the catalog moves to that release.<br>`npm view typeid-js@<catalog version> dependencies.uuid` | #976 |
| SD-3 | `package.json` — pnpm override `deepmerge-ts@<8.0.0` | `@prisma/config` declares deepmerge-ts >= 8.0.0, **or** the optional `prisma` peer stops being installed. No workspace package uses Prisma. The subtree exists only because `autoInstallPeers` is on.<br>`npm view @prisma/config dependencies.deepmerge-ts` | #976 |
| SD-4 | `package.json` — pnpm override `esbuild` (unconditional) | `vite` and `drizzle-kit` both declare ranges that admit the pinned version. Today they cap at `^0.27.0` and `^0.25.4`, so a free resolve makes three copies.<br>`npm view vite dependencies.esbuild` | #1010 |
| SD-5 | `package.json` — pnpm override `esbuild@<0.25.0` | **Already true. This key is dead** — SD-4 matches every esbuild spec and shadows it. Remove it. | #976 |
| SD-6 | Ten Dockerfiles — `apt-get upgrade -y` in the runtime stage | The pinned base image is rebuilt on the current Debian point release. The digest sits on 13.6 while 13.7 is out, and a digest bump does not help until the Docker Official Image is rebuilt.<br>`docker run --rm python:3.14-slim-trixie dpkg-query -W -f='${Version}' perl-base` | #720, #994, #1022 |
| SD-7 | `services/outlook-semantic-mcp/deploy/Dockerfile` — `perl-base` in the explicit install set | Same as SD-6. Only this one service lists it. `apt-get upgrade -y` should already cover it, so confirm before you keep it. | #1013 |
| SD-8 | Four `pyproject.toml` files — `[tool.uv] override-dependencies` for `fastmcp` | `unique-mcp` declares a `fastmcp` range that admits 4.x. Note the versions drifted: `office-365-mcp` overrides to 4.0.2, the other three to 4.0.3. | — |
| SD-9 | Four Python Dockerfiles — `rm -rf` of pip | pip stops carrying an SBOM that declares vulnerable packages. Review rather than revert: not shipping a package installer is good practice on its own. | #1033 |

### Not on this list

Permanent hardening does not belong here, because it has no upstream exit. That covers the removal
of npm, npx and pnpm from the runtime images, and the Trivy scanner scope.

### Open problems in this table

- **SD-5 is removable today.** It does nothing while SD-4 exists.
- **SD-3 has a gap.** Its upper bound is 8.0.0 but its value is 8.0.2, so 8.0.0 and 8.0.1 fall
  through unpatched. The parent pins 7.1.5 exactly, so nothing reaches the gap today. An override
  key must use the form `pkg@<X: X`, or it is a ceiling as well as a floor.
- **SD-4 and SD-7 have no recorded reason.** Neither names a CVE, and SD-7 arrived inside a PR about
  OAuth token handling. A comment there claims a `perl-base` version pin that the install line does
  not carry.
