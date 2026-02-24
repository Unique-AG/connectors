---
name: commit-generator
description: Analyze git changes and generate conventional commit messages following the project's standards. Use when creating commit messages or when the user asks for help with commits.
---

# Commit Message Generator

## Quick Start

Run this skill to automatically analyze your current changes and generate an appropriate conventional commit message:

```bash
# Check git status first
git status

# Generate commit message
bash .cursor/skills/commit-generator/scripts/analyze-changes.sh

# Implementation: Pure bash script using only git commands
# No external dependencies or Node.js required
```

## How It Works

1. **Analyze Changes**: Uses git commands to check only staged files (what will actually be committed)
2. **Determine Type**: Based on file patterns and change types:
   - `feat`: New features, API additions (new files, feature flags)
   - `fix`: Bug fixes, error handling improvements
   - `docs`: Documentation files (.md, README changes)
   - `chore`: Maintenance, tooling, dependencies
   - `refactor`: Code restructuring (file renames, reorganization)
   - `test`: Test files, test-related changes
   - `build`: Build config, CI/CD, deployment files

3. **Identify Scope**: Maps file paths to project scopes:
   - `services/sharepoint-connector/**` → `sharepoint-connector`
   - `packages/logger/**` → `logger`
   - `.github/**` → `ci`
   - `*.md`, configs → `main`
   - `package.json`, `pnpm-lock.yaml` → `deps`

4. **Generate Description**: Creates concise, present-tense descriptions based on:
   - File names and types changed
   - Function/component names added/modified
   - Common patterns in the codebase

## Examples

### Feature Addition
**Changes**: Added new sync method in SharePoint connector
**Generated**: `feat(sharepoint-connector): add incremental sync for large document libraries`

### Bug Fix
**Changes**: Fixed error handling in logger utility
**Generated**: `fix(logger): resolve memory leak in Pino transport configuration`

### Documentation
**Changes**: Updated README and API docs
**Generated**: `docs(main): update deployment instructions and API documentation`

### Dependencies
**Changes**: Updated package.json versions
**Generated**: `chore(deps): update TypeScript to version 5.9.2`

### Multiple Scopes
**Changes**: Modified both logger package and mcp-oauth package
**Generated**: `refactor(logger,mcp-oauth): consolidate error handling patterns`

## Usage Patterns

### Before Committing
```bash
# Make your changes
git add .

# Generate commit message
# Skill analyzes changes and outputs: feat(sharepoint-connector): add document versioning support

# Use the generated message
git commit -m "feat(sharepoint-connector): add document versioning support"
```

### For Specific Changes
```bash
# Stage specific files
git add services/sharepoint-connector/src/new-feature.ts
git add packages/logger/src/improved-logging.ts

# Generate message for staged changes only
# Output: feat(sharepoint-connector,logger): implement enhanced logging for sync operations
```

### Review and Edit
```bash
# Generate suggestion
# Output: fix(teams-mcp): resolve authentication timeout issue

# Edit if needed
git commit -m "fix(teams-mcp): resolve authentication timeout in OAuth flow"
```

## Type Detection Logic

### feat
- New files in `src/` directories
- Addition of exported functions/classes
- New API endpoints or features
- Feature flag implementations

### fix
- Error handling improvements
- Bug-related comments or TODOs
- Exception catching additions
- Validation logic enhancements

### docs
- Changes to `.md` files
- README updates
- Code comments additions
- Documentation generation

### chore
- Dependency updates
- Configuration file changes
- Tooling improvements
- Build script modifications

### refactor
- File renames/moves
- Code reorganization
- Import/export restructuring
- Function signature changes

### test
- New test files
- Test utility additions
- Test coverage improvements
- Mock/stub implementations

## Scope Mapping

| File Pattern | Scope | Example |
|-------------|-------|---------|
| `services/factset-mcp/**` | `factset-mcp` | Database connection fixes |
| `services/outlook-mcp/**` | `outlook-mcp` | Email processing features |
| `services/sharepoint-connector/**` | `sharepoint-connector` | Document sync operations |
| `services/teams-mcp/**` | `teams-mcp` | Chat integration updates |
| `packages/aes-gcm-encryption/**` | `aes-gcm-encryption` | Encryption algorithm changes |
| `packages/instrumentation/**` | `instrumentation` | Metrics collection updates |
| `packages/logger/**` | `logger` | Logging improvements |
| `packages/mcp-oauth/**` | `mcp-oauth` | Authentication flow fixes |
| `packages/mcp-server-module/**` | `mcp-server-module` | Server module updates |
| `packages/probe/**` | `probe` | Health check modifications |
| `.github/**` | `ci` | Workflow improvements |
| `*.md`, root configs | `main` | Documentation updates |
| `**/package.json`, lockfiles | `deps` | Dependency management |

## Description Generation

The skill analyzes:

1. **File Names**: `user-authentication.service.ts` → "implement user authentication"
2. **Function Names**: `syncDocuments()` → "add document synchronization"
3. **Change Patterns**: Added error handling → "improve error handling"
4. **Directory Context**: `api/` changes → API-related descriptions

## Multi-Scope Handling

When changes span multiple scopes:

1. **Primary Scope**: Most affected files
2. **Secondary Scopes**: Other affected areas
3. **Combined Output**: `type(primary,secondary): description`

Example: Changes in both logger and mcp-oauth packages → `refactor(logger,mcp-oauth): consolidate error handling`

## Integration with Development Workflow

### Pre-commit Hook
```bash
#!/bin/bash
# .git/hooks/prepare-commit-msg
# Generate commit message suggestion
```

### IDE Integration
- Run before committing in Cursor
- Quick suggestions during development
- Validation against conventional commit standards

## Troubleshooting

### Unclear Changes
If the generated message doesn't fit:
- Stage changes in smaller chunks
- Provide more specific file names
- Add descriptive comments to functions

### Wrong Scope Detected
- Check file location matches intended scope
- Move files if organization is incorrect
- Use manual scope override if needed

### Generic Descriptions
For complex changes:
- Break into smaller commits
- Add inline comments explaining changes
- Use more descriptive file/function names

## Best Practices

1. **Small, Focused Commits**: Easier to analyze and generate accurate messages
2. **Descriptive Names**: Clear file and function names improve generation
3. **Logical Grouping**: Related changes together for coherent descriptions
4. **Review Generated Messages**: Always verify before committing

## Additional Resources

- See AGENTS.md for complete conventional commits guide
- Check project README for scope definitions
- Review recent commits for examples and patterns