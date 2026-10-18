from functools import partial
from urllib.parse import urlsplit
from typing import Any

import anyio
from fastapi import HTTPException
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations


READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
CREATE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)


def principal(ctx, write=False):
    request = ctx.request_context.request
    auth = getattr(request.state, 'auth', None) if request is not None else None
    if not auth or not auth.get('token_id') or not auth.get('user'):
        raise ToolError('401: A personal wiki API token is required.')
    if write and (auth.get('read_only', False) or auth['user'].get('role') not in ('editor', 'admin')):
        raise ToolError('403: This user or token cannot edit wiki pages.')
    return dict(auth['user'])


async def invoke(callback, *args, **kwargs):
    try:
        return await anyio.to_thread.run_sync(partial(callback, *args, **kwargs))
    except HTTPException as error:
        if error.status_code == 409:
            message = 'The wiki changed. Read the page and list pages again before retrying with fresh revisions.'
        elif error.status_code < 500:
            message = str(error.detail)
        else:
            message = 'The wiki could not complete this operation. Try again later.'
        raise ToolError(f'{error.status_code}: {message}') from None
    except Exception:
        raise ToolError('500: The wiki could not complete this operation. Try again later.') from None


def create_mcp(origin, service):
    server = MCPServer('wiki', instructions='Read and edit wiki notes as the authenticated user. Read a note before updating it. Never overwrite a conflict without reading the latest version.')

    @server.tool(description='List the wiki page hierarchy and its current tree revision. Paths refer to wiki Markdown notes, never arbitrary filesystem files.', annotations=READ, structured_output=True)
    async def wiki_list_pages(ctx: Context) -> dict[str, Any]:
        principal(ctx)
        return await invoke(service.list_pages)

    @server.tool(description='Search wiki page titles and content. Returns matching note paths; read a page before changing it.', annotations=READ, structured_output=True)
    async def wiki_search(query: str, ctx: Context, limit: int = 20) -> dict[str, Any]:
        principal(ctx)
        if not query.strip() or len(query) > 500 or not 1 <= limit <= 50:
            raise ToolError('400: Supply a nonempty query of at most 500 characters and a limit between 1 and 50.')
        return await invoke(service.search, query, limit)

    @server.tool(description='Read a wiki note, including its Markdown body, title, path and revision. Keep this revision for an update.', annotations=READ, structured_output=True)
    async def wiki_read_page(path: str, ctx: Context) -> dict[str, Any]:
        principal(ctx)
        return await invoke(service.read_page, path)

    @server.tool(description='Create a new Markdown note in an existing section. Use an empty section for the root. Does not overwrite existing pages.', annotations=CREATE, structured_output=True)
    async def wiki_create_page(section: str, slug: str, title: str, body: str, ctx: Context) -> dict[str, Any]:
        actor = principal(ctx, write=True)
        return await invoke(service.create_page, section, slug, title, body, actor=actor)

    @server.tool(description='Update a wiki note using the revision returned by wiki_read_page. A conflict requires rereading and reconciling the latest page; never retry blindly.', annotations=WRITE, structured_output=True)
    async def wiki_update_page(path: str, revision: str, title: str, body: str, ctx: Context) -> dict[str, Any]:
        actor = principal(ctx, write=True)
        return await invoke(service.update_page, path, revision, title, body, actor=actor)

    @server.tool(description='Delete one Markdown note using the current tree_revision from wiki_list_pages. Does not delete directories or their contents. Confirm the intended note before deleting.', annotations=WRITE, structured_output=True)
    async def wiki_delete_page(path: str, tree_revision: str, ctx: Context) -> dict[str, Any]:
        actor = principal(ctx, write=True)
        return await invoke(service.delete_page, path, tree_revision, actor=actor)

    parsed = urlsplit(origin)
    http_app = server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        streamable_http_path='/mcp',
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[parsed.netloc],
            allowed_origins=[f'{parsed.scheme}://{parsed.netloc}'],
        ),
    )
    return server, http_app
