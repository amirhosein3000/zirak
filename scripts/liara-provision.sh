#!/bin/sh
# Make sure the Liara apps (and the API app's data disk) exist before a deploy. Safe to re-run.
#   LIARA_API_TOKEN=... [LIARA_TEAM_ID=...] sh scripts/liara-provision.sh [api|web|both]
# Creating an app costs money, so it only happens when LIARA_PLAN is set (see `liara plan list`, for
# example a "g2" plan); otherwise a missing app stops here with instructions. Uses the same Liara API
# endpoints as the official CLI (`liara app create`, `liara disk create`) without its interactive prompts.
set -eu
: "${LIARA_API_TOKEN:?set LIARA_API_TOKEN}"
TARGET="${1:-both}"
API_APP="${LIARA_API_APP:-zirak-api}"
WEB_APP="${LIARA_WEB_APP:-zirak-web}"
BASE="https://api.liara.ir"
TEAM="${LIARA_TEAM_ID:-}"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

# liara METHOD PATH [JSON] -> prints the HTTP status; the body is in $TMP
liara_api() {
  if [ -n "${3:-}" ]; then
    curl -sS -o "$TMP" -w '%{http_code}' -X "$1" -H "Authorization: Bearer $LIARA_API_TOKEN" \
      -H "Content-Type: application/json" --data "$3" "$BASE/$2?teamID=$TEAM"
  else
    curl -sS -o "$TMP" -w '%{http_code}' -X "$1" -H "Authorization: Bearer $LIARA_API_TOKEN" "$BASE/$2?teamID=$TEAM"
  fi
}

ensure_app() {
  status="$(liara_api GET "v1/projects/$1")"
  case "$status" in
    200) echo "app $1: exists"; return 0 ;;
    401|403) echo "::error::Liara refused the token ($status). Check LIARA_API_TOKEN and LIARA_TEAM_ID." >&2; exit 1 ;;
    404) ;;
    *) echo "::error::Liara answered $status for app $1: $(cat "$TMP")" >&2; exit 1 ;;
  esac
  if [ -z "${LIARA_PLAN:-}" ]; then
    echo "::error::Liara app '$1' does not exist. Create it once in console.liara.ir (platform: Docker, region: Iran)," \
      "or set the LIARA_PLAN repository variable (a plan id from 'liara plan list') so the deploy creates it." >&2
    exit 1
  fi
  body="{\"name\":\"$1\",\"planID\":\"$LIARA_PLAN\",\"platform\":\"docker\",\"bundlePlanID\":\"${LIARA_FEATURE_PLAN:-standard}\"}"
  status="$(liara_api POST "v1/projects/" "$body")"
  case "$status" in
    2*) echo "app $1: created (plan $LIARA_PLAN)" ;;
    *) echo "::error::could not create app $1 ($status): $(cat "$TMP")" >&2; exit 1 ;;
  esac
}

ensure_disk() {
  # No "list disks" endpoint is used by the CLI, so try to create and accept "already there".
  status="$(liara_api POST "v1/projects/$1/disks" "{\"name\":\"$2\",\"size\":${LIARA_DISK_GB:-5}}")"
  case "$status" in
    2*) echo "disk $2 on $1: created (${LIARA_DISK_GB:-5} GB)" ;;
    409) echo "disk $2 on $1: exists" ;;
    *)
      if grep -qi "exist" "$TMP"; then
        echo "disk $2 on $1: exists"
      else
        echo "::warning::disk $2 on $1 not created ($status): $(cat "$TMP"). Create it in the console if the deploy reports disk_not_found."
      fi
      ;;
  esac
}

if [ "$TARGET" != "web" ]; then
  ensure_app "$API_APP"
  ensure_disk "$API_APP" zirak-data
fi
if [ "$TARGET" != "api" ]; then
  ensure_app "$WEB_APP"
fi
