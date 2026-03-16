# PR Proposal

## Title
fix(confluence-connector): allow deletion guard to pass when new files are being added

## Description
- The `validateNoAccidentalFullDeletion` guard was blocking syncs even when genuinely new pages were being added alongside deletions, causing spaces to get permanently stuck
- When all files would be deleted, now compares submitted keys against deleted keys to distinguish key format bugs (overlap → block) from legitimate content replacement (no overlap → allow with warning)
- Ports the same fix applied to the SharePoint connector on 2026-03-13
