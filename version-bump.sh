#!/bin/bash

# TODO: replace with release-please.
# version-bump.sh - Script to bump version numbers across package.json, Chart.yaml, and values.yaml
# Usage: ./version-bump.sh <service-name> <new-version>
# Example: ./version-bump.sh outlook-mcp 0.0.3

set -e  # Exit on any error

# Check if correct number of arguments provided
if [ $# -ne 2 ]; then
    echo "Error: Incorrect number of arguments"
    echo "Usage: $0 <service-name> <new-version>"
    echo "Example: $0 outlook-mcp 0.0.3"
    exit 1
fi

SERVICE_NAME="$1"
NEW_VERSION="$2"

# Validate version format (basic semantic version check)
if ! [[ "$NEW_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-.*)?$ ]]; then
    echo "Error: Version must be in semantic version format (e.g., 1.2.3 or 1.2.3-beta.1)"
    exit 1
fi

# Define paths
SERVICE_DIR="services/$SERVICE_NAME"
PACKAGE_JSON="$SERVICE_DIR/package.json"
CHART_DIR="$SERVICE_DIR/deploy/helm-charts/$SERVICE_NAME"
CHART_YAML="$CHART_DIR/Chart.yaml"
VALUES_YAML="$CHART_DIR/values.yaml"

# Check if service directory exists
if [ ! -d "$SERVICE_DIR" ]; then
    echo "Error: Service directory '$SERVICE_DIR' does not exist"
    echo "Available services:"
    ls -1 services/
    exit 1
fi

# Check if package.json exists
if [ ! -f "$PACKAGE_JSON" ]; then
    echo "Error: package.json not found at '$PACKAGE_JSON'"
    exit 1
fi

echo "Run tests & code coverage"
pnpm test:coverage --filter=@unique-ag/$SERVICE_NAME

echo "Updating version to $NEW_VERSION for service: $SERVICE_NAME"

# Update package.json
echo "Updating $PACKAGE_JSON..."
# Use sed to replace the version field in package.json
# This handles both "version": "x.x.x" and "version":"x.x.x" formats
sed -i '' "s/\"version\":[[:space:]]*\"[^\"]*\"/\"version\": \"$NEW_VERSION\"/" "$PACKAGE_JSON"

if [ $? -eq 0 ]; then
    echo "✓ Updated package.json version to $NEW_VERSION"
else
    echo "✗ Failed to update package.json"
    exit 1
fi

# Check if chart directory exists
if [ -d "$CHART_DIR" ]; then
    echo "Found chart directory, updating Chart.yaml and values.yaml..."
    
    # Update Chart.yaml
    if [ -f "$CHART_YAML" ]; then
        echo "Updating $CHART_YAML..."
        # Update both version and appVersion fields
        sed -i '' "s/^version:[[:space:]]*[^[:space:]]*.*$/version: $NEW_VERSION # TODO: Tag must be auto-injected via release process from package.json/" "$CHART_YAML"
        sed -i '' "s/^appVersion:[[:space:]]*[^[:space:]]*.*$/appVersion: $NEW_VERSION # FIXME: this does not work as intended sadly, this version does not trickle down into the dependency/" "$CHART_YAML"
        
        if [ $? -eq 0 ]; then
            echo "✓ Updated Chart.yaml version and appVersion to $NEW_VERSION"
        else
            echo "✗ Failed to update Chart.yaml"
            exit 1
        fi
    else
        echo "Warning: Chart.yaml not found at '$CHART_YAML'"
    fi
    
    # Update values.yaml
    if [ -f "$VALUES_YAML" ]; then
        echo "Updating $VALUES_YAML..."
        # Update the tag field under server.image
        sed -i '' "s/tag:[[:space:]]*[^[:space:]]*.*$/tag: $NEW_VERSION # TODO: Tag must be auto-injected via release process from package.json/" "$VALUES_YAML"
        
        if [ $? -eq 0 ]; then
            echo "✓ Updated values.yaml tag to $NEW_VERSION"
        else
            echo "✗ Failed to update values.yaml"
            exit 1
        fi
    else
        echo "Warning: values.yaml not found at '$VALUES_YAML'"
    fi
else
    echo "No chart directory found for $SERVICE_NAME, skipping Chart.yaml and values.yaml updates"
fi

echo ""
echo "🎉 Version bump completed successfully!"
echo "Updated $SERVICE_NAME to version $NEW_VERSION"
echo ""
echo "Files updated:"
echo "  - $PACKAGE_JSON"
if [ -d "$CHART_DIR" ]; then
    if [ -f "$CHART_YAML" ]; then
        echo "  - $CHART_YAML"
    fi
    if [ -f "$VALUES_YAML" ]; then
        echo "  - $VALUES_YAML"
    fi
fi
echo ""
echo "Don't forget to commit your changes:"
echo "git add ."
echo "git commit -m \"bump: $SERVICE_NAME v$NEW_VERSION\""
