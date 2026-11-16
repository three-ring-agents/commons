#!/usr/bin/env bash
# install-commons-local.sh — Bootstrap script for local hosts (Mac Mini / Linux running antigravity-cli `agy`)
# Clones or updates ~/.gemini/commons (dont-tell-the-wifi) and symlinks shared skills into ~/.gemini/antigravity-cli/skills/
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:${HOME}/.local/bin:${PATH}"

STATE_DIR="${HOME}/.gemini/state"
MESH_DIR="${HOME}/.gemini/mesh"
COMMONS_DIR="${HOME}/.gemini/commons"
CLI_SKILLS_DIR="${HOME}/.gemini/antigravity-cli/skills"
AGENTS_SKILLS_DIR="${HOME}/.agents/skills"
CLAUDE_SKILLS_DIR="${HOME}/.claude/skills"
CONFIG_FILE="${STATE_DIR}/config.json"

COMMONS_GITHUB_REPO="three-ring-agents/commons"
if [ -f "${CONFIG_FILE}" ]; then
  COMMONS_GITHUB_REPO="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("commons_github_repo","three-ring-agents/commons"))' "${CONFIG_FILE}" 2>/dev/null || echo "three-ring-agents/commons")"
fi

echo "=== Setting up Antigravity Shared Commons (dont-tell-the-wifi) on $(hostname) ==="
mkdir -p "${HOME}/.gemini" "${CLI_SKILLS_DIR}"

if [ ! -d "${COMMONS_DIR}/.git" ]; then
  if command -v gh >/dev/null 2>&1 && gh repo view "${COMMONS_GITHUB_REPO}" >/dev/null 2>&1; then
    echo "Cloning https://github.com/${COMMONS_GITHUB_REPO}.git into ${COMMONS_DIR}..."
    git clone "https://github.com/${COMMONS_GITHUB_REPO}.git" "${COMMONS_DIR}"
  elif [ -f "./dont-tell-the-wifi.bundle" ]; then
    echo "Cloning from local dont-tell-the-wifi.bundle into ${COMMONS_DIR}..."
    git clone "./dont-tell-the-wifi.bundle" "${COMMONS_DIR}"
  fi
fi

# Create GitHub repo on local host if not yet created and push main
if command -v gh >/dev/null 2>&1 && [ -d "${COMMONS_DIR}/.git" ]; then
  if ! gh repo view "${COMMONS_GITHUB_REPO}" >/dev/null 2>&1; then
    echo "Creating private GitHub repo ${COMMONS_GITHUB_REPO}..."
    gh repo create "${COMMONS_GITHUB_REPO}" --private || true
  fi
  git -C "${COMMONS_DIR}" remote set-url origin "https://github.com/${COMMONS_GITHUB_REPO}.git" 2>/dev/null || \
    git -C "${COMMONS_DIR}" remote add origin "https://github.com/${COMMONS_GITHUB_REPO}.git"
  git -C "${COMMONS_DIR}" push -u origin main || true
else
  echo "Note: 'gh' CLI not found on PATH. Install via 'brew install gh && gh auth login' to push to GitHub."
fi

# Symlink all shared skills in ~/.gemini/commons/skills/* into ~/.gemini/antigravity-cli/skills/
# (plus cross-harness AAIF SKILL.md directories ~/.agents/skills/ and ~/.claude/skills/ if present)
chmod +x "${COMMONS_DIR}/skills/sync-commons/scripts/sync_commons.sh" \
         "${COMMONS_DIR}/skills/sync-commons/scripts/redact_check.py" \
         "${COMMONS_DIR}/skills/collab-roe/scripts/gdocs_comment.py" \
         "${COMMONS_DIR}/skills/collab-roe/scripts/watch_doc_once.py" \
         "${COMMONS_DIR}/skills/redact-gate/scripts/scrub.py" \
         "${COMMONS_DIR}/skills/redact-gate/scripts/verify_skill_safety.py" \
         "${COMMONS_DIR}/skills/gchat/scripts/gchat.py" \
         "${COMMONS_DIR}/playbooks/unifi-security-hardening/scripts/verify_household_slo.py" 2>/dev/null || true

mkdir -p "${MESH_DIR}" "${AGENTS_SKILLS_DIR}" "${CLAUDE_SKILLS_DIR}"

for skill_path in "${COMMONS_DIR}"/skills/*; do
  if [ -d "${skill_path}" ] && [ -f "${skill_path}/SKILL.md" ]; then
    skill_name="$(basename "${skill_path}")"
    for target_skills_dir in "${CLI_SKILLS_DIR}" "${AGENTS_SKILLS_DIR}" "${CLAUDE_SKILLS_DIR}"; do
      ln -sfn "${skill_path}" "${target_skills_dir}/${skill_name}"
    done
    echo "  ✓ Linked shared skill: /${skill_name} -> ${skill_path} (CLI, ~/.agents/skills, ~/.claude/skills)"
  fi
done

echo ""
echo "=== Shared Commons Setup Complete! ==="
echo "• Local Commons Path:  ${COMMONS_DIR}"
echo "• Shared GitHub Repo:  https://github.com/${COMMONS_GITHUB_REPO}"
echo "• Shared Drive Folder: https://drive.google.com/drive/folders/{{GOOGLE_DRIVE_FOLDER_ID}}"
