# Five-minute Claude Code setup

This setup uses the published base package; on Python 3.10+ it already includes
the MCP SDK.

## 1. Install and check

```bash
python -m pip install --upgrade citationguard
citeguard status
```

For isolation, use `pipx install citationguard`. For a one-shot MCP process,
use `uvx --from citationguard citeguard-mcp`.

## 2. Register the stdio server

```json
{
  "mcpServers": {
    "citeguard": {"command": "citeguard-mcp"}
  }
}
```

For `uvx`:

```json
{
  "mcpServers": {
    "citeguard": {
      "command": "uvx",
      "args": ["--from", "citationguard", "citeguard-mcp"]
    }
  }
}
```

Restart or reconnect the client after changing MCP configuration.

## 3. Install the agent skill

From the project where Claude Code should use CiteGuard:

```bash
citeguard skill install --client claude --scope project
```

The installer is idempotent and refuses to overwrite a different skill unless
you pass `--force`.

## 4. Verify the connection

Ask the agent to call `citeguard_status_tool`, then:

```text
Verify “Attention Is All You Need”, arXiv:1706.03762, year 2017.
```

The result should retain the identifier-authority lookup and must not turn a
source outage into a fabrication claim.

## 5. Audit a bibliography

```text
Audit the references in this file with CiteGuard. Show high-risk items first,
preserve source line numbers, and do not edit anything without confirmation.
```

For more than 100 references, split the input into numbered chunks. See
[MCP setup](mcp_setup.md), [tool errors](error_codes.md), and
[troubleshooting](troubleshooting.md).
