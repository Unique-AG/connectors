---
name: check-all
description: Run comprehensive code quality checks for the service.
disable-model-invocation: true
---

# /check-all

Run comprehensive code quality checks for the SharePoint connector service.

**What it does:**
**Comprehensive checks** - Runs `npm run check-all` which includes auto-fixing linting issues and TypeScript type checking

**When to use:**
- Before committing code changes
- After making significant modifications
- To ensure code quality standards are met
- As part of CI/CD pipeline validation

**Note:** This focuses on code style and type safety. For full testing including unit and integration tests, use separate test commands.