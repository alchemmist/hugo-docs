# MCP access

The wiki runtime can expose a Streamable HTTP MCP endpoint so agents can read and publish notes as a local user. The static Hugo theme alone does not run an MCP server.

## Enable the endpoint

Set one option in `/config/wiki.yaml` and restart the runtime:

```yaml
mcp:
  enabled: true
```

For Helm, set `config.mcp.enabled: true` in the existing values file. `WIKI_MCP_ENABLED=true` overrides the file setting when configuring the runtime directly through its environment.

The endpoint is the canonical wiki URL followed by `/mcp`: for example, `https://wiki.example.com/mcp` or `https://wiki.example.com/docs/mcp`. Preserve the configured prefix at the reverse proxy, just as for the browser UI. Use HTTPS outside localhost.

MCP defaults to disabled: its endpoint returns 404 and the account page hides token management. Disabling the feature does not remove notes or accounts.

## Create a personal token

1. Sign in to `/admin` using your own wiki account.
2. Open **MCP access** and create a token with a descriptive name, such as `coding-agent`.
3. Choose read-only access if the agent only needs to consult documentation. Tokens expire after 90 days by default; the supported lifetime is 1–365 days.
4. Copy the secret immediately into the agent’s secret storage. It is shown only once; the server stores a hash.

Send it as `Authorization: Bearer <token>` on every MCP request. Tokens are personal, revocable credentials; do not put them in article content, URLs, Git, Helm values or shared agent configuration. Revoke a token on `/admin` when a client no longer needs access. Changing or resetting the user’s password, changing their role, or disabling the account revokes their tokens; issue a new token after such changes.

This is personal-token authentication, without OAuth or OIDC. Use a client that supports Streamable HTTP and a custom Authorization header. Clients that require an interactive OAuth flow cannot connect through that flow.

## Permissions

| User role | MCP access |
| --- | --- |
| Reader | List, search and read published notes |
| Editor | Read and create, update or delete notes |
| Administrator | The same note operations as an editor |

A read-only token further restricts an editor or administrator to read operations. Every request checks the account’s current enabled state and role. A token does not bypass permissions or grant access to account administration, server configuration or arbitrary files. Even when browser reading is public, MCP requests require a token.

## Agent workflow

Agents discover these tools through `tools/list`:

| Tool | Arguments and result |
| --- | --- |
| `wiki_list_pages` | No arguments; returns the page hierarchy and its `revision` |
| `wiki_search` | `query`, optional `limit` (1–50, default 20); returns matching note paths and excerpts |
| `wiki_read_page` | `path`; returns Markdown `body`, `title`, `path` and the page’s `revision` |
| `wiki_create_page` | `section`, `slug`, `title`, `body`; creates a note in an existing section (empty `section` means root) |
| `wiki_update_page` | `path`, page `revision`, `title`, `body`; updates an existing note |
| `wiki_delete_page` | `path`, `tree_revision`; deletes one plain `.md` note |

Use listing or search to find a note, then read its source and revision before updating it. For deletion, pass the hierarchy’s `revision` from `wiki_list_pages` as `tree_revision`; a page revision is not interchangeable with it. Deletion cannot remove directories, `_index.md` or `index.md`. A stale revision is rejected: read the latest page and hierarchy and reconcile changes instead of blindly retrying a write.

Writes use the same validation and atomic publication pipeline as browser editing. Create/update results include the published page in `pages[]`, including its new `revision`. All successful writes return the updated hierarchy `revision`; delete returns an empty `pages` list. Accepted content is available without waiting for CI. Git synchronization, when configured, follows asynchronously. Publication audit metadata records the token’s user; the configured Git commit identity is unchanged. A token does not give an agent a shell or direct repository access.

## Test a connection

Set `WIKI_MCP_TOKEN` in your shell from the newly issued secret and set the endpoint for your installation. Do not paste the secret into a script that will be committed.

```sh
export WIKI_MCP_URL='https://wiki.example.com/mcp'
INITIALIZE_RESPONSE=$(curl --fail-with-body "$WIKI_MCP_URL" \
  -H "Authorization: Bearer $WIKI_MCP_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"wiki-check","version":"1.0"}}}')
export WIKI_MCP_PROTOCOL=$(printf '%s' "$INITIALIZE_RESPONSE" | jq -er '.result.protocolVersion')
curl --fail-with-body "$WIKI_MCP_URL" \
  -H "Authorization: Bearer $WIKI_MCP_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "MCP-Protocol-Version: $WIKI_MCP_PROTOCOL" \
  --data '{"jsonrpc":"2.0","method":"notifications/initialized"}'
```

This shell example uses `jq`, offers the supported `2025-03-26` protocol and uses the server’s negotiated version on subsequent requests. A normal MCP client performs initialization and protocol negotiation automatically. The runtime is stateless, so no session identifier is needed. To inspect tool schemas manually after initialization:

```sh
curl --fail-with-body "$WIKI_MCP_URL" \
  -H "Authorization: Bearer $WIKI_MCP_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "MCP-Protocol-Version: $WIKI_MCP_PROTOCOL" \
  --data '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

List pages, then read an actual note path from the returned hierarchy:

```sh
wiki_mcp_call() {
  curl --fail-with-body "$WIKI_MCP_URL" \
    -H "Authorization: Bearer $WIKI_MCP_TOKEN" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -H "MCP-Protocol-Version: $WIKI_MCP_PROTOCOL" \
    --data "$1"
}
wiki_mcp_call '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"wiki_list_pages","arguments":{}}}'
PAGE_RESPONSE=$(wiki_mcp_call '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"wiki_read_page","arguments":{"path":"getting-started.md"}}}')
printf '%s' "$PAGE_RESPONSE" | jq -e '.result | select(.isError != true) | .structuredContent'
```

Replace `getting-started.md` with an existing note. To publish an intentional edit, write the replacement Markdown body into `updated-note.md`, inspect it, and build the call from the last successful read:

```sh
UPDATE_REQUEST=$(printf '%s' "$PAGE_RESPONSE" | jq -e --rawfile body updated-note.md '
  .result | select(.isError != true) | .structuredContent
  | {jsonrpc: "2.0", id: 5, method: "tools/call", params: {
      name: "wiki_update_page",
      arguments: {path: .path, revision: .revision, title: .title, body: $body}
    }}')
wiki_mcp_call "$UPDATE_REQUEST" | jq '.result'
```

Tool errors can arrive in a successful HTTP response with `result.isError: true`; check that field before treating a write as published.

A 404 usually means MCP is disabled or the endpoint prefix is wrong. A 401 means the credential is missing, expired, revoked or its account is disabled. If writing is denied, check the user’s role and the token’s read-only setting. Revision conflicts require reading the current note before trying again.

Back up the full runtime volume, including the account database and accepted publication state. Protect that backup as account data: the database contains token hashes and account records, while issued token secrets belong in the client’s secret store. Git alone is not a backup of accounts or token records. Restoring an old database may restore token records that were revoked after the backup; revoke those tokens again before reopening access.
