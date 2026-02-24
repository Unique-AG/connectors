---
name: commit-msg
description: Generate a conventional commit message from staged git changes.
disable-model-invocation: true
---

# /commit-msg

Generate a properly formatted conventional commit message by analyzing your current git changes.

**What it does:**
**Automatic commit message generator** - Analyzes only staged changes, determines the appropriate type and scope, and generates a conventional commit message that follows your project's standards.

**When to use:**
- After making changes and before committing
- To ensure commit messages follow conventional commit format
- When you want Cursor to suggest the appropriate type and scope

**How it works:**
1. Analyzes only staged files (what will actually be committed)
2. Determines commit type based on file patterns and changes
3. Identifies affected scopes based on file paths
4. Generates concise, descriptive commit message

**Examples:**
```
/commit-msg
```
Output: `feat(sharepoint-connector): add incremental sync for large document libraries`

```
/commit-msg
```
Output: `fix(logger): resolve memory leak in Pino transport`

**Supported patterns:**
- **feat**: New features, API additions, user-facing changes
- **fix**: Bug fixes, error corrections
- **docs**: Documentation changes
- **chore**: Maintenance, tooling, dependency updates
- **refactor**: Code restructuring without behavior changes
- **test**: Adding or fixing tests
- **build**: Build system, CI/CD changes
- **revert**: Reverting previous commits

**Scopes detected automatically:**
- Services: factset-mcp, outlook-mcp, sharepoint-connector, teams-mcp
- Packages: aes-gcm-encryption, instrumentation, logger, mcp-oauth, mcp-server-module, probe
- Special: ci (.github/**), main (root files), deps (package files)

**Multi-scope support:**
When changes affect multiple scopes, automatically combines them:
`feat(teams-mcp,mcp-oauth): add shared authentication feature`

**Technical details:**
This command executes: `bash .cursor/skills/commit-generator/scripts/analyze-changes.sh`