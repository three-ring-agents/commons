#!/usr/bin/env bash
# sync_commons.sh — Dual GitHub + Google Drive Bundle Sync for ~/.gemini/commons (dont-tell-the-wifi)
# Enforces the 3-Stage Pre-Push Redaction Gate (redact_check.py) before every commit & push.
set -euo pipefail

STATE_DIR="${ANTIGRAVITY_STATE_DIR:-$HOME/.gemini/state}"
MESH_DIR="${ANTIGRAVITY_MESH_DIR:-$HOME/.gemini/mesh}"
COMMONS_DIR="${ANTIGRAVITY_COMMONS_DIR:-$HOME/.gemini/commons}"
CONFIG_FILE="$STATE_DIR/config.json"
MESH_FILE="$MESH_DIR/mesh.json"

# Dynamically resolve config via Ring 1 (~/.gemini/state/config.json) -> Ring 2 (~/.gemini/mesh/mesh.json) -> Ring 3 default
read_cfg() {
  local key="$1"
  local default_val="$2"
  python3 - "$CONFIG_FILE" "$MESH_FILE" "$key" "$default_val" <<'PY'
import json, os, sys
cfg_path, mesh_path, k, d = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
for p in (cfg_path, mesh_path):
    if os.path.isfile(p):
        try:
            data = json.load(open(p, encoding="utf-8"))
            val = data.get(k)
            if val and not str(val).startswith("{{"):
                print(val)
                sys.exit(0)
        except Exception:
            pass
print(d)
PY
}

COMMONS_GITHUB_REPO="$(read_cfg "commons_github_repo" "three-ring-agents/commons")"
COMMONS_DRIVE_FOLDER_ID="$(read_cfg "commons_drive_folder_id" "{{GOOGLE_DRIVE_FOLDER_ID}}")"
PROPOSAL_DOC_ID="$(read_cfg "proposal_doc_id" "{{GOOGLE_DOC_ID}}")"
BUNDLE_NAME="commons.bundle"

IS_CLOUD_VM=0
if [ -d "/shared/user/.gemini" ]; then
  IS_CLOUD_VM=1
  GIT_WORK_DIR="/home/antigravity/dont-tell-the-wifi"
else
  GIT_WORK_DIR="$COMMONS_DIR"
fi

GH_BIN="gh"
if ! command -v gh >/dev/null 2>&1 && [ -x "/opt/antigravity/plugins/github/skills/github/scripts/gh" ]; then
  GH_BIN="/opt/antigravity/plugins/github/skills/github/scripts/gh"
fi

GDRIVE_BIN=""
if command -v gdrive >/dev/null 2>&1; then
  GDRIVE_BIN="gdrive"
elif [ -x "/opt/antigravity/plugins/gdrive/skills/gdrive/scripts/gdrive" ]; then
  GDRIVE_BIN="/opt/antigravity/plugins/gdrive/skills/gdrive/scripts/gdrive"
fi

copy_commons_safe() {
  python3 - "$1" "$2" <<'PY'
import os, sys
src_root, dst_root = sys.argv[1], sys.argv[2]
skip_dirs = {".git", "__pycache__"}
for r, dirs, files in os.walk(src_root):
    dirs[:] = [d for d in dirs if d not in skip_dirs]
    rel = os.path.relpath(r, src_root)
    target_dir = dst_root if rel == "." else os.path.join(dst_root, rel)
    os.makedirs(target_dir, exist_ok=True)
    for f in files:
        if f.endswith(".bundle"):
            continue
        sf = os.path.join(r, f)
        df = os.path.join(target_dir, f)
        with open(sf, "rb") as rf, open(df, "wb") as wf:
            wf.write(rf.read())
PY
}

ensure_commons_git_repo() {
  mkdir -p "$COMMONS_DIR"
  rm -rf "$COMMONS_DIR/.git" 2>/dev/null || true
  if [ "$IS_CLOUD_VM" -eq 1 ]; then
    if [ ! -d "$GIT_WORK_DIR/.git" ]; then
      rm -rf "$GIT_WORK_DIR"
      if [ -f "$COMMONS_DIR/$BUNDLE_NAME" ]; then
        cp /dev/null /tmp/commons-init.bundle 2>/dev/null || true
        cat "$COMMONS_DIR/$BUNDLE_NAME" > /tmp/commons-init.bundle
        git clone /tmp/commons-init.bundle "$GIT_WORK_DIR" >/dev/null 2>&1 || true
        rm -f /tmp/commons-init.bundle
      fi
      if [ ! -d "$GIT_WORK_DIR/.git" ]; then
        mkdir -p "$GIT_WORK_DIR"
        git -C "$GIT_WORK_DIR" init -b main >/dev/null
      fi
      git -C "$GIT_WORK_DIR" remote set-url origin "https://github.com/$COMMONS_GITHUB_REPO.git" 2>/dev/null || \
        git -C "$GIT_WORK_DIR" remote add origin "https://github.com/$COMMONS_GITHUB_REPO.git"
    fi
    copy_commons_safe "$COMMONS_DIR" "$GIT_WORK_DIR"
  else
    if [ ! -d "$GIT_WORK_DIR/.git" ]; then
      git -C "$GIT_WORK_DIR" init -b main >/dev/null
      git -C "$GIT_WORK_DIR" remote add origin "https://github.com/$COMMONS_GITHUB_REPO.git" 2>/dev/null || true
    fi
  fi
}

sync_git_to_commons_dir() {
  if [ "$IS_CLOUD_VM" -eq 1 ] && [ -d "$GIT_WORK_DIR/.git" ]; then
    copy_commons_safe "$GIT_WORK_DIR" "$COMMONS_DIR"
    if git -C "$GIT_WORK_DIR" rev-parse --verify HEAD >/dev/null 2>&1; then
      git -C "$GIT_WORK_DIR" bundle create "/tmp/$BUNDLE_NAME" --all
      cat "/tmp/$BUNDLE_NAME" > "$COMMONS_DIR/$BUNDLE_NAME"
    fi
  fi
}

upload_or_update_drive_file() {
  local local_path="$1"
  local filename
  filename="$(basename "$local_path")"
  if [ -z "$GDRIVE_BIN" ]; then
    return 0
  fi
  local existing_id
  existing_id="$("$GDRIVE_BIN" readonly search --parent-id "$COMMONS_DRIVE_FOLDER_ID" --name-exact "$filename" --json 2>/dev/null | python3 -c 'import sys,json; data=json.load(sys.stdin); files=data if isinstance(data,list) else data.get("files",[]); print(files[0]["id"] if files else "")' 2>/dev/null || true)"
  if [ -n "$existing_id" ]; then
    "$GDRIVE_BIN" mutate update "$existing_id" "$local_path" >/dev/null
    echo "  ✓ Updated $filename in shared Commons Drive folder ($existing_id)"
  else
    "$GDRIVE_BIN" mutate upload "$local_path" --parent "$COMMONS_DRIVE_FOLDER_ID" >/dev/null
    echo "  ✓ Uploaded $filename to shared Commons Drive folder ($COMMONS_DRIVE_FOLDER_ID)"
  fi
}

cmd="${1:-status}"
shift || true

case "$cmd" in
  status)
    ensure_commons_git_repo
    echo "=== Antigravity Shared Commons (dont-tell-the-wifi) Status ==="
    echo "Commons dir:          $COMMONS_DIR"
    echo "Git working dir:      $GIT_WORK_DIR"
    echo "Shared GitHub repo:   https://github.com/$COMMONS_GITHUB_REPO"
    echo "Shared Drive folder:  https://drive.google.com/drive/folders/$COMMONS_DRIVE_FOLDER_ID"
    echo "Proposal Doc:         https://docs.google.com/document/d/$PROPOSAL_DOC_ID/edit"
    echo ""
    python3 "$COMMONS_DIR/skills/sync-commons/scripts/redact_check.py" scan
    echo ""
    git -C "$GIT_WORK_DIR" status -sb
    echo "Latest commit: $(git -C "$GIT_WORK_DIR" log -1 --oneline 2>/dev/null || echo 'none')"
    ;;

  pull)
    echo "=== Pulling Shared Commons (dont-tell-the-wifi) ==="
    ensure_commons_git_repo
    if "$GH_BIN" repo view "$COMMONS_GITHUB_REPO" >/dev/null 2>&1; then
      echo "Pulling from GitHub ($COMMONS_GITHUB_REPO)..."
      git -C "$GIT_WORK_DIR" pull --rebase origin main || true
    elif [ -n "$GDRIVE_BIN" ]; then
      bundle_id="$("$GDRIVE_BIN" readonly search --parent-id "$COMMONS_DRIVE_FOLDER_ID" --name-exact "$BUNDLE_NAME" --json 2>/dev/null | python3 -c 'import sys,json; data=json.load(sys.stdin); files=data if isinstance(data,list) else data.get("files",[]); print(files[0]["id"] if files else "")' 2>/dev/null || true)"
      if [ -n "$bundle_id" ]; then
        echo "Fetching $BUNDLE_NAME from shared Google Drive folder ($bundle_id)..."
        rm -f /tmp/commons-pull.bundle
        "$GDRIVE_BIN" readonly download "$bundle_id" --out /tmp/commons-pull.bundle >/dev/null
        git -C "$GIT_WORK_DIR" pull --rebase /tmp/commons-pull.bundle main || true
        rm -f /tmp/commons-pull.bundle
      fi
    fi
    sync_git_to_commons_dir
    if [ "$IS_CLOUD_VM" -eq 0 ] && [ -x "$COMMONS_DIR/install-commons-local.sh" ]; then
      "$COMMONS_DIR/install-commons-local.sh"
    fi
    echo "✓ Pull complete."
    ;;

  push)
    msg="${1:-Sync shared commons ($(date -u +%Y-%m-%dT%H:%M:%SZ))}"
    echo "=== Pushing Shared Commons (dont-tell-the-wifi) ==="
    echo "[Gate 1/3] Running Pre-Push Redaction Gate (redact_check.py)..."
    python3 "$COMMONS_DIR/skills/sync-commons/scripts/redact_check.py" scan

    ensure_commons_git_repo
    git -C "$GIT_WORK_DIR" add -A
    if ! git -C "$GIT_WORK_DIR" diff --cached --quiet; then
      git -C "$GIT_WORK_DIR" commit -m "$msg"
    fi
    sync_git_to_commons_dir

    # 1. Push to GitHub if repo exists and is accessible
    if "$GH_BIN" repo view "$COMMONS_GITHUB_REPO" >/dev/null 2>&1; then
      echo "Pushing directly to main on GitHub ($COMMONS_GITHUB_REPO)..."
      git -C "$GIT_WORK_DIR" push -u origin main && echo "  ✓ Pushed to GitHub ($COMMONS_GITHUB_REPO)" || echo "  ! GitHub push skipped (syncing via shared Drive bundle)"
    else
      echo "  i GitHub repo $COMMONS_GITHUB_REPO not yet created or granted to Cloud GitHub App; syncing via shared Google Drive bundle."
    fi

    # 2. Mirror Git bundle and key artifacts to shared Google Drive folder
    if [ -n "$GDRIVE_BIN" ]; then
      echo "Syncing $BUNDLE_NAME and README/bootstrap scripts to shared Google Drive folder ($COMMONS_DRIVE_FOLDER_ID)..."
      git -C "$GIT_WORK_DIR" bundle create "/tmp/$BUNDLE_NAME" --all
      upload_or_update_drive_file "/tmp/$BUNDLE_NAME"
      rm -f "/tmp/$BUNDLE_NAME"
      [ -f "$GIT_WORK_DIR/README.md" ] && upload_or_update_drive_file "$GIT_WORK_DIR/README.md"
      [ -f "$GIT_WORK_DIR/install-commons-local.sh" ] && upload_or_update_drive_file "$GIT_WORK_DIR/install-commons-local.sh"
    fi
    echo "✓ Shared Commons sync complete."
    ;;

  *)
    echo "Usage: $0 {status|pull|push [commit_msg]}"
    exit 1
    ;;
esac
