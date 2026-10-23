# Label explanation

Use a label from this list. Do not invent one. Jira labels cannot contain a space.

| Label | Use |
| --- | --- |
| `mcp-server` | Connectors work. Every issue this skill files, including sub-tasks. |
| `mcp-server/unplanned` | Work that already happened and was not planned. Added on top of `mcp-server`. See [unplanned-work.md](unplanned-work.md). |

```
project = UN AND labels = "mcp-server" AND labels = "mcp-server/unplanned" ORDER BY created DESC
```
