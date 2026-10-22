#!/bin/sh
# Deploy to Liara from your own machine (the same as the GitHub Action). Needs: npm install -g @liara/cli
#   LIARA_API_TOKEN=... LIARA_TEAM_ID=... sh scripts/deploy-liara.sh [api|web|both]
# Never commit the token; pass it in the environment.
set -eu
: "${LIARA_API_TOKEN:?set LIARA_API_TOKEN}"
TARGET="${1:-both}"
API_APP="${LIARA_API_APP:-zirak-api}"
WEB_APP="${LIARA_WEB_APP:-zirak-web}"
API_URL="${LIARA_API_URL:-https://$API_APP.liara.run}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMMIT="$(git -C "$ROOT" rev-parse HEAD)"
if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then
  echo "commit your changes first: the deployed code must equal a commit" >&2
  exit 1
fi
sh "$ROOT/scripts/liara-provision.sh" "$TARGET"
set -- --api-token "$LIARA_API_TOKEN" --platform docker --build-location iran --message "commit $COMMIT"
if [ -n "${LIARA_TEAM_ID:-}" ]; then
  set -- "$@" --team-id "$LIARA_TEAM_ID"
fi
if [ "$TARGET" != "web" ]; then
  (cd "$ROOT/backend" && liara deploy --app "$API_APP" --port 8000 --build-arg "GIT_COMMIT=$COMMIT" "$@")
fi
if [ "$TARGET" != "api" ]; then
  (cd "$ROOT/frontend" && liara deploy --app "$WEB_APP" --port 3000 --build-arg "NEXT_PUBLIC_API_URL=$API_URL" "$@")
fi
