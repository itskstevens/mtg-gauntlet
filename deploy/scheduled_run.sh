#!/usr/bin/env bash
# Scheduled gauntlet run, driven by mtg-gauntlet.timer.
#
# Env overrides (put these in /etc/default/mtg-gauntlet):
#   MTG_DECK       deck to run                  (default: codie)
#   MTG_SERIES     series per category          (default: 300)
#   MTG_JOBS       worker processes, 0 = one/core (default: 0)
#   MTG_TAG        results folder suffix        (default: adhoc)
#   MTG_PUSH       1 to commit+push results    (default: 1)
#   MTG_CATEGORIES comma-separated subset      (default: all)
set -euo pipefail

REPO="${MTG_REPO:-/home/kevin/mtg-gauntlet}"
PY="$REPO/.venv/bin/python"

# Sourced before anything reads it. systemd also passes this via EnvironmentFile=, which
# is why the misordering was not obvious, but a hand-run would have silently ignored it.
# shellcheck disable=SC1091
[ -f /etc/default/mtg-gauntlet ] && . /etc/default/mtg-gauntlet
: "${MTG_REPO:=$REPO}"

cd "$REPO"

DECK="${MTG_DECK:-codie}"
SERIES="${MTG_SERIES:-300}"
JOBS="${MTG_JOBS:-0}"
TAG="${MTG_TAG:-adhoc}"
PUSH="${MTG_PUSH:-1}"
RUN_ID="$(date -u +%Y%m%d-%H%M%S)-timer"

# The timer must never overlap a manual job: the engine is one queue, so check for a
# live worker and skip rather than fight over the cores.
if pgrep -f "gauntlet.py (run|variants)" >/dev/null 2>&1; then
    echo "scheduled run: an engine job is already running, skipping" >&2
    exit 0
fi

ARGS=(run "$DECK" --series "$SERIES" --jobs "$JOBS" --tag "$TAG" --run-id "$RUN_ID")
[ -n "${MTG_CATEGORIES:-}" ] && ARGS+=(--categories "$MTG_CATEGORIES")

echo "scheduled run: ${ARGS[*]}"
"$PY" gauntlet.py "${ARGS[@]}"

if [ "$PUSH" = "1" ]; then
    # flock so a scheduled commit can't interleave with a job worker's own push
    exec 9>/tmp/mtg-gauntlet-push.lock
    flock 9
    git add results decks
    git commit -m "$DECK: scheduled run $(date -u +%F) ($SERIES series)" || echo "(nothing to commit)"
    git pull --rebase --autostash
    git push
fi