#!/bin/bash

# Create test attachments directory
TARGET_DIR="/Users/lorand/workspace/unique/connectors/test-attachments"
mkdir -p "$TARGET_DIR"

# Create a temporary file with lorem ipsum content
TEMP_FILE=$(mktemp)
cat > "$TEMP_FILE" << 'EOF'
Lorem ipsum dolor sit amet, consectetur adipiscing elit.
Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.
Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.
EOF

# Copy the file 150 times with unique names
for i in {1..150}; do
  filename=$(printf "test-attachment-%03d.txt" "$i")
  cp "$TEMP_FILE" "$TARGET_DIR/$filename"
  echo "Created: $filename"
done

# Clean up temporary file
rm "$TEMP_FILE"

echo "Successfully created 150 test attachment files in $TARGET_DIR"
