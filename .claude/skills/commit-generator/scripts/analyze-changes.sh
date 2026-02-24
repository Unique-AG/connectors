#!/bin/bash

# Git-based Commit Message Generator
# Analyzes staged files using git commands only

echo "Analyzing staged changes..."

# Get staged files
STAGED_FILES=$(git diff --cached --name-only)

if [ -z "$STAGED_FILES" ]; then
    echo "No staged files found. Stage some files first with 'git add'."
    exit 1
fi

echo "Staged files:"
echo "$STAGED_FILES" | sed 's/^/- /'
echo ""

# Determine scopes based on file paths
SCOPES=""
MAIN_SCOPE=false
SHAREPOINT_SCOPE=false
LOGGING_SCOPE=false
OAUTH_SCOPE=false
CI_SCOPE=false
DEPS_SCOPE=false

while IFS= read -r file; do
    if [[ "$file" == AGENTS.md ]] || [[ "$file" == *.md ]] || [[ "$file" != */* ]]; then
        MAIN_SCOPE=true
    fi

    if [[ "$file" == services/sharepoint-connector/** ]]; then
        SHAREPOINT_SCOPE=true
    fi

    if [[ "$file" == packages/logger/** ]]; then
        LOGGING_SCOPE=true
    fi

    if [[ "$file" == packages/mcp-oauth/** ]]; then
        OAUTH_SCOPE=true
    fi

    if [[ "$file" == .github/** ]]; then
        CI_SCOPE=true
    fi

    if [[ "$file" == */package.json ]] || [[ "$file" == pnpm-lock.yaml ]]; then
        DEPS_SCOPE=true
    fi
done <<< "$STAGED_FILES"

# Build scope string
SCOPE_LIST=""
if [ "$MAIN_SCOPE" = true ]; then SCOPE_LIST="main"; fi
if [ "$SHAREPOINT_SCOPE" = true ]; then SCOPE_LIST="${SCOPE_LIST:+$SCOPE_LIST,}sharepoint-connector"; fi
if [ "$LOGGING_SCOPE" = true ]; then SCOPE_LIST="${SCOPE_LIST:+$SCOPE_LIST,}logger"; fi
if [ "$OAUTH_SCOPE" = true ]; then SCOPE_LIST="${SCOPE_LIST:+$SCOPE_LIST,}mcp-oauth"; fi
if [ "$CI_SCOPE" = true ]; then SCOPE_LIST="${SCOPE_LIST:+$SCOPE_LIST,}ci"; fi
if [ "$DEPS_SCOPE" = true ]; then SCOPE_LIST="${SCOPE_LIST:+$SCOPE_LIST,}deps"; fi

# Determine commit type
HAS_NEW_FILES=false
HAS_FIXES=false
HAS_TESTS=false
HAS_DOCS=false
HAS_DEPS=false

while IFS= read -r file; do
    # Check if file is new
    if ! git ls-files --error-unmatch "$file" >/dev/null 2>&1; then
        HAS_NEW_FILES=true
    fi

    # Check for test files
    if [[ "$file" == *.spec.ts ]] || [[ "$file" == *.test.ts ]]; then
        HAS_TESTS=true
    fi

    # Check for docs
    if [[ "$file" == *.md ]]; then
        HAS_DOCS=true
    fi

    # Check for deps
    if [[ "$file" == */package.json ]] || [[ "$file" == pnpm-lock.yaml ]]; then
        HAS_DEPS=true
    fi

    # Check for fix indicators in file content (if file exists)
    if [ -f "$file" ]; then
        if grep -qi "fix\|bug\|error\|resolve\|handle" "$file" 2>/dev/null; then
            HAS_FIXES=true
        fi
    fi
done <<< "$STAGED_FILES"

# Determine type
if [ "$HAS_FIXES" = true ]; then
    TYPE="fix"
elif [ "$HAS_NEW_FILES" = true ]; then
    TYPE="feat"
elif [ "$HAS_TESTS" = true ]; then
    TYPE="test"
elif [ "$HAS_DOCS" = true ]; then
    TYPE="docs"
elif [ "$HAS_DEPS" = true ]; then
    TYPE="chore"
else
    TYPE="chore"
fi

# Generate description
if [ "$TYPE" = "feat" ]; then
    DESCRIPTION="add new functionality"
elif [ "$TYPE" = "fix" ]; then
    DESCRIPTION="fix issues"
elif [ "$TYPE" = "test" ]; then
    DESCRIPTION="add tests"
elif [ "$TYPE" = "docs" ]; then
    DESCRIPTION="update documentation"
elif [ "$TYPE" = "chore" ] && [ "$HAS_DEPS" = true ]; then
    DESCRIPTION="update dependencies"
else
    DESCRIPTION="update codebase"
fi

# Add scope context
if [ "$SCOPE_LIST" != "main" ]; then
    DESCRIPTION="$DESCRIPTION $SCOPE_LIST"
fi

# Generate final commit message
COMMIT_MESSAGE="$TYPE($SCOPE_LIST): $DESCRIPTION"

echo "Generated commit message:"
echo "\"$COMMIT_MESSAGE\""
echo ""
echo "To use this message:"
echo "git commit -m \"$COMMIT_MESSAGE\""