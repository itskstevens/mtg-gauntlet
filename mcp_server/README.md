# mtg-gauntlet MCP server (homelab)

Lets a Claude chat start gauntlet runs on the homelab (Ryzen 7 5700, 16 threads) instead of the 2-core cloud
workspace. Results are committed and pushed to GitHub when a job finishes, so any session reads them from the repo.

It exposes six narrow tools, never a general shell:

| Tool | What it does |
|---|---|
| `list_decks()` | Decks under `decks/`, whether each has a pilot, and the machine's core count |
| `run_gauntlet(deck, series=300, jobs=0, swaps=None, categories=None, tag="", push=True)` | Starts a run (or a swap test when `swaps` is given) in a detached background worker and returns a job id at once. `jobs=0` means all cores but two. |
| `job_status(job_id="")` | State (`queued`, `running`, `done`, `failed`, `cancelled`, `lost`), elapsed minutes, log tail. No id means the latest job. |
| `list_jobs()` | Recent jobs |
| `cancel_job(job_id)` | Stops a job. Nothing is committed. |
| `sync()` | `git pull --rebase`, so decks and pilots pushed from elsewhere are available |

Only one job runs at a time. Workers are detached, so a job keeps running if the SSH connection or chat drops.
Job state and logs live in `mcp_server/jobs/` (git-ignored).

## Setup on the homelab (Ubuntu)

1. Clone the repo somewhere permanent, e.g. `~/mtg-gauntlet`, and make sure `git push` works non-interactively
   from it (SSH deploy key or a credential helper). The worker pushes results with plain `git push`.
2. Create a virtualenv and install dependencies:
   ```bash
   cd ~/mtg-gauntlet
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt -r mcp_server/requirements.txt
   ```
3. Set a commit identity for the repo if the machine has none:
   `git config user.name "Kevin Stevens"` and `git config user.email "itskstevens@gmail.com"`.
4. Test it. This should list six tools and exit cleanly:
   ```bash
   .venv/bin/python - <<'EOF'
   import asyncio
   from mcp import ClientSession, StdioServerParameters
   from mcp.client.stdio import stdio_client
   async def main():
       p = StdioServerParameters(command='.venv/bin/python', args=['mcp_server/server.py'])
       async with stdio_client(p) as (r, w):
           async with ClientSession(r, w) as s:
               await s.initialize()
               print([t.name for t in (await s.list_tools()).tools])
   asyncio.run(main())
   EOF
   ```
5. Optional smoke test of a real job without pushing: call `run_gauntlet("codie", series=2, categories=["Typal"],
   tag="mcp-test", push=False)` from the test above, poll `job_status`, then delete `results/codie/*-mcp-test`.

## Connect it to Claude: option A, through the Mac (recommended)

Nothing is exposed to the internet. The Claude desktop app on the Mac runs the server over SSH (stdio), and its
tools appear in claude.ai chats linked to the Mac, the same way `tradingview-mcp` does.

1. The Mac needs key-based SSH to the homelab with no password prompt (Tailscale hostname is fine).
   Check with `ssh <user>@<homelab> true`.
2. Add this to `~/Library/Application Support/Claude/claude_desktop_config.json` on the Mac, under `mcpServers`,
   using the real user, host and path:
   ```json
   "mtg-gauntlet-homelab": {
     "command": "ssh",
     "args": ["-o", "BatchMode=yes", "<user>@<homelab>",
              "cd ~/mtg-gauntlet && exec .venv/bin/python mcp_server/server.py"]
   }
   ```
3. Restart the Claude desktop app. The Mac must be awake with the app open for the tools to be available.

## Connect it to Claude: option B, remote connector

For use with the Mac off. Run `python mcp_server/server.py --http 8765` as a service on the homelab. It binds to
127.0.0.1 only. Publish it through Cloudflare Tunnel or Tailscale Funnel with authentication in front of it, then
add the public URL in claude.ai as a custom connector. Only do this with authentication: anyone who reaches the
endpoint can start jobs and push to the repo.

## Notes

- Pinned to the MCP Python SDK v1 (`mcp<2`). SDK v2 renamed `FastMCP` to `MCPServer`.
- A full 300-series pass is about 15 CPU-minutes, so roughly 1.5–2 minutes with 14 jobs. A swap test with three
  swaps runs four passes.
- The homelab has had intermittent shutdowns. If one kills a job, `job_status` reports it as `lost`. Nothing is
  pushed, so just start it again.
