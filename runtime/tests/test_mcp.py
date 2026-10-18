import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import sys
import unittest

import httpx2
from fastapi import HTTPException
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.applications import Starlette
from starlette.routing import Route

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mcp_server import create_mcp


class Notes:
    def __init__(self):
        self.actors = []

    def list_pages(self):
        return {'nodes': [{'path': 'hello.md'}], 'revision': 'tree-1'}

    def read_page(self, path):
        if path == 'broken.md':
            raise RuntimeError('secret database password')
        if path != 'hello.md':
            raise HTTPException(404, 'Page not found')
        return {'path': path, 'title': 'Hello', 'body': 'World', 'revision': 'page-1'}

    def search(self, query, limit):
        return {'results': [self.read_page('hello.md')][:limit]}

    def create_page(self, section, slug, title, body, actor):
        self.actors.append(actor)
        return {'path': f'{slug}.md', 'title': title, 'body': body}

    def update_page(self, path, revision, title, body, actor):
        if revision != 'page-1':
            raise HTTPException(409, 'internal revision details')
        self.actors.append(actor)
        return {'path': path, 'revision': 'page-2'}

    def delete_page(self, path, tree_revision, actor):
        self.actors.append(actor)
        return {'deleted': path}


class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.notes = Notes()
        self.server, self.http_app = create_mcp('https://wiki.example', self.notes)
        self.ready = asyncio.Event()
        self.stop = asyncio.Event()
        async def lifespan():
            async with self.server.session_manager.run():
                self.ready.set()
                await self.stop.wait()
        self.manager_task = asyncio.create_task(lifespan())
        await self.ready.wait()

    async def asyncTearDown(self):
        self.stop.set()
        await self.manager_task

    @asynccontextmanager
    async def client(self, username='alice', role='editor', read_only=False, prefix=''):
        app = Starlette(routes=[Route('/mcp', self.http_app, methods=['GET', 'POST', 'DELETE'])])

        async def authenticated(scope, receive, send):
            scope['state'] = {'auth': {'user': {'id': username, 'username': username, 'role': role},
                                       'token_id': 'test-token', 'read_only': read_only}}
            await app(scope, receive, send)

        transport = httpx2.ASGITransport(app=authenticated, root_path=prefix)
        async with httpx2.AsyncClient(transport=transport) as http:
            async with streamable_http_client(f'https://wiki.example{prefix}/mcp', http_client=http) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    yield session

    async def test_real_client_discovers_and_reads_notes(self):
        async with self.client() as client:
            tools = (await client.list_tools()).tools
            self.assertEqual({tool.name for tool in tools}, {
                'wiki_list_pages', 'wiki_read_page', 'wiki_search',
                'wiki_create_page', 'wiki_update_page', 'wiki_delete_page',
            })
            for tool in tools:
                self.assertNotIn('ctx', tool.input_schema.get('properties', {}))
            page = await client.call_tool('wiki_read_page', {'path': 'hello.md'})
            self.assertFalse(page.is_error)
            self.assertEqual(page.structured_content['revision'], 'page-1')
            tree = await client.call_tool('wiki_list_pages', {})
            self.assertEqual(tree.structured_content['revision'], 'tree-1')
            search = await client.call_tool('wiki_search', {'query': 'hello'})
            self.assertEqual(search.structured_content['results'][0]['path'], 'hello.md')

    async def test_reader_and_read_only_tokens_cannot_write(self):
        for role, read_only in [('reader', False), ('admin', True)]:
            async with self.client(role=role, read_only=read_only) as client:
                result = await client.call_tool('wiki_delete_page', {'path': 'hello.md', 'tree_revision': 'tree-1'})
                self.assertTrue(result.is_error)
                self.assertIn('403', result.content[0].text)
        self.assertEqual(self.notes.actors, [])

    async def test_editor_can_update_and_delete(self):
        async with self.client() as client:
            result = await client.call_tool('wiki_update_page', {
                'path': 'hello.md', 'revision': 'page-1', 'title': 'Hello', 'body': 'New',
            })
            self.assertFalse(result.is_error)
            self.assertEqual(result.structured_content['revision'], 'page-2')
            result = await client.call_tool('wiki_delete_page', {'path': 'hello.md', 'tree_revision': 'tree-1'})
            self.assertFalse(result.is_error)
            self.assertEqual(result.structured_content['deleted'], 'hello.md')
        self.assertEqual([actor['username'] for actor in self.notes.actors], ['alice', 'alice'])

    async def test_conflict_and_unexpected_errors_are_safe(self):
        async with self.client() as client:
            result = await client.call_tool('wiki_update_page', {
                'path': 'hello.md', 'revision': 'old', 'title': 'Hello', 'body': 'New',
            })
            self.assertTrue(result.is_error)
            self.assertIn('409', result.content[0].text)
            self.assertIn('fresh revisions', result.content[0].text)
            result = await client.call_tool('wiki_read_page', {'path': 'broken.md'})
            self.assertTrue(result.is_error)
            self.assertNotIn('password', result.content[0].text)
            result = await client.call_tool('wiki_search', {'query': 'x', 'limit': 101})
            self.assertTrue(result.is_error)

    async def test_concurrent_clients_keep_their_own_identity(self):
        async def create(username):
            async with self.client(username=username) as client:
                result = await client.call_tool('wiki_create_page', {
                    'section': '', 'slug': username, 'title': username, 'body': 'New',
                })
                self.assertFalse(result.is_error)
        await asyncio.gather(create('alice'), create('bob'))
        self.assertEqual({actor['username'] for actor in self.notes.actors}, {'alice', 'bob'})

    async def test_subpath_mount(self):
        async with self.client(prefix='/docs') as client:
            result = await client.call_tool('wiki_read_page', {'path': 'hello.md'})
            self.assertFalse(result.is_error)

    async def test_transport_rejects_foreign_host_and_origin(self):
        transport = httpx2.ASGITransport(app=self.http_app)
        payload = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'},
        }}
        async with httpx2.AsyncClient(transport=transport) as client:
            headers = {'accept': 'application/json, text/event-stream'}
            response = await client.post('https://evil.example/mcp', headers=headers, json=payload)
            self.assertEqual(response.status_code, 421)
            response = await client.post('https://wiki.example/mcp', headers={**headers, 'origin': 'https://evil.example'}, json=payload)
            self.assertEqual(response.status_code, 403)


if __name__ == '__main__':
    unittest.main()
