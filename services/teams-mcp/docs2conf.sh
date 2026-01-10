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

CONFLUENCE_SPACE_KEY='~624ebe8d45ece00069ce737e'
CONFLUENCE_PARENT_PAGE_ID='1788117060'

CONFLUENCE_USER_NAME="$(op read 'op://wkh73trucskob7ycx4w7asxnsu/wgpgh7lyqhkxso3wtn2vwgp4qi/username')"
CONFLUENCE_API_KEY="$(op read 'op://wkh73trucskob7ycx4w7asxnsu/wgpgh7lyqhkxso3wtn2vwgp4qi/password')"

echo -e "\n-- Publishing docs to Confluence --\n"
docker run --rm \
    -v "$DOCS_DIR:/data" \
    -e CONFLUENCE_DOMAIN='unique-ch.atlassian.net' \
    -e CONFLUENCE_PATH='/wiki/' \
    -e CONFLUENCE_USER_NAME="$CONFLUENCE_USER_NAME" \
    -e CONFLUENCE_API_KEY="$CONFLUENCE_API_KEY" \
    -e CONFLUENCE_SPACE_KEY="$CONFLUENCE_SPACE_KEY" \
    leventehunyadi/md2conf:latest \
    -r "$CONFLUENCE_PARENT_PAGE_ID" \
    --generated-by 'This page is auto-generated from the <a href="https://github.com/unique-ag/connectors/tree/main/services/teams-mcp/docs">teams-mcp docs</a>. Do not edit manually.' \
    ./

echo -e "\n-- Publishing complete --\n"