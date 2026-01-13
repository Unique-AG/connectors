#!/bin/bash
# SPDX-SnippetBegin
# SPDX-License-Identifier: Apache-2.0
# SPDX-SnippetCopyrightText: 2025 © Unique AG
# SPDX-SnippetEnd
# This script publishes the teams-mcp docs to Confluence using md2conf.
# Reference: https://github.com/hunyadi/md2conf
set -eux

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DOCS_DIR="$SCRIPT_DIR/docs"

# role/developer vault – Atlassian Service User - Unique Code Publisher (Dev)
# ⚠️ production publisher uses GitHub Actions secrets
CONFLUENCE_USER_NAME="$(op read 'op://s6nhjzc6dvkbn734b4vfquxcl4/svli6rcupjkpbv5qd3kjnjq6ua/username')"
CONFLUENCE_API_KEY="$(op read 'op://s6nhjzc6dvkbn734b4vfquxcl4/svli6rcupjkpbv5qd3kjnjq6ua/67rp6kkazshlruauqjjfpiv6jm')"

echo -e "\n-- Publishing docs to Confluence --\n"
docker run --rm \
    -v "$DOCS_DIR:/data" \
    -e CONFLUENCE_DOMAIN='unique-ch.atlassian.net' \
    -e CONFLUENCE_PATH='/wiki/' \
    -e CONFLUENCE_USER_NAME="$CONFLUENCE_USER_NAME" \
    -e CONFLUENCE_API_KEY="$CONFLUENCE_API_KEY" \
    leventehunyadi/md2conf:latest \
    --generated-by 'This pages are auto-generated from the <a href="https://github.com/unique-ag/connectors/tree/main/services/teams-mcp/docs">teams-mcp docs</a>.' \
    ./

echo -e "\n-- Publishing complete --\n"