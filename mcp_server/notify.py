"""Completion notifications for gauntlet jobs.

Posts a short message when a job finishes. Works with any of:
  - ntfy:        MTG_NOTIFY_URL=https://ntfy.sh/<topic>
  - Discord:     MTG_NOTIFY_URL=https://discord.com/api/webhooks/<id>/<token>
  - Slack:       MTG_NOTIFY_URL=https://hooks.slack.com/services/...
  - Home Assist: MTG_NOTIFY_URL=http://homeassistant:8123/api/services/notify/<svc>

Best effort by design: a notification failure never fails a job, because the results are
already committed by the time we get here. Every notification is also appended to
mcp_server/jobs/notifications.log so there is a local record if the webhook is down.
"""
import json
import os
import urllib.request

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'jobs', 'notifications.log')


def _post(url, payload):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json', 'Title': 'MTG gauntlet'},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status


def notify(job_id, deck, ok, detail=''):
    title = f"gauntlet {deck}: {'done' if ok else 'FAILED'}"
    body = f"{job_id} {detail}".strip()
    line = f"{title} - {body}"
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, 'a') as f:
            f.write(line + '\n')
    except OSError:
        pass

    url = os.environ.get('MTG_NOTIFY_URL', '').strip()
    if not url:
        return {'sent': False, 'reason': 'MTG_NOTIFY_URL not set', 'logged': line}
    try:
        if 'discord' in url:
            status = _post(url, {'content': f'**{title}**\n{body}'})
        elif 'hooks.slack' in url:
            status = _post(url, {'text': f'{title}\n{body}'})
        elif 'homeassistant' in url:
            status = _post(url, {'message': f'{title}: {body}'})
        else:
            status = _post(url, {'topic': 'mtg-gauntlet', 'title': title, 'message': body})
        return {'sent': True, 'status': status, 'logged': line}
    except Exception as e:
        return {'sent': False, 'reason': repr(e)[:200], 'logged': line}