#!/bin/sh
# Container entrypoint (Docker / Liara): the API, plus the trading agent in the same container.
#
#   ZIRAK_AGENT        off (default) | shadow | live | "live shadow"   which agent runs to start
#   ZIRAK_AGENT_CONFIG agent config (default /app/config/challenge.json)
#   ZIRAK_BOOTSTRAP    true = on first start (no trained model yet) backfill Wallex history and train
#
# A crashed agent is restarted after 15 s and resumes its run (state in /data/runs/). An agent that exits
# cleanly (kill switch, guard kill, challenge over) is NOT restarted. The API keeps serving /agent either way.
set -u
CONFIG="${ZIRAK_AGENT_CONFIG:-/app/config/challenge.json}"
MODES="$(echo "${ZIRAK_AGENT:-off}" | tr ',' ' ')"

supervise() {
  mode="$1"
  while true; do
    if [ "$mode" = "live" ]; then
      zirak agent live --config "$CONFIG" --i-understand-this-is-real-money
    else
      zirak agent shadow --config "$CONFIG"
    fi
    code=$?
    if [ "$code" -eq 0 ]; then
      echo "[start.sh] $mode agent stopped cleanly; not restarting (zirak reset-kill + redeploy to resume)"
      return
    fi
    echo "[start.sh] $mode agent exited with $code; restarting in 15 s"
    sleep 15
  done
}

if [ "$MODES" != "off" ]; then
  (
    name="$(python -c "import json,sys;print(json.load(open(sys.argv[1]))['name'])" "$CONFIG")"
    if [ "${ZIRAK_BOOTSTRAP:-false}" = "true" ] && [ ! -f "${DATA_DIR:-/data}/models/$name/model_card.json" ]; then
      echo "[start.sh] bootstrap: backfill + train"
      zirak backfill --days-1m "${ZIRAK_BACKFILL_DAYS_1M:-45}" --days-1h 180 && zirak agent train --config "$CONFIG" \
        || echo "[start.sh] bootstrap failed; the agent starts with the smoothed-prior model"
    fi
    for mode in $MODES; do
      case "$mode" in
        live|shadow) supervise "$mode" & ;;
        *) echo "[start.sh] unknown ZIRAK_AGENT mode '$mode' (use off, shadow, live)" ;;
      esac
    done
    wait
  ) &
fi

exec uvicorn zirak.api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
