#!/bin/bash
# sync_scripts_to_dataset_roots.sh
# Sync all code scripts from a source directory to all dataset roots for NLP training
# Usage: ./sync_scripts_to_dataset_roots.sh /path/to/source

SRC_DIR="$1"
if [ -z "$SRC_DIR" ]; then
  echo "Usage: $0 /path/to/source"
  exit 1
fi

# List of dataset roots (update as needed)
DATASET_ROOTS=(
  "/mnt/dataset_storage"
  "/mnt/shared"
  "/mnt/toshiba"
  "/mnt/toshiba/dataset_external/selected_github_repos"
  "/mnt/webcode"
  "/app/implementation_outputs"
  "/app/implementations"
  "/mnt/dataset_storage/skynetv1"
)

# File patterns to sync (add more as needed)
PATTERNS=("*.py" "*.js" "*.ts" "*.java" "*.go" "*.rs" "*.cpp" "*.c" "*.cs")

for ROOT in "${DATASET_ROOTS[@]}"; do
  if [ -d "$ROOT" ]; then
    echo "Syncing to $ROOT ..."
    for PAT in "${PATTERNS[@]}"; do
      rsync -av --ignore-existing "$SRC_DIR"/$PAT "$ROOT" 2>/dev/null
    done
  else
    echo "[WARN] Dataset root $ROOT does not exist, skipping."
  fi
done

echo "Sync complete."
