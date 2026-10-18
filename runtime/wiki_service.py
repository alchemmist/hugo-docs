from types import SimpleNamespace

from fastapi import HTTPException


class WikiService:
    def __init__(self, *, lock, sync, tree, read, batch):
        self.lock = lock
        self.sync = sync
        self.tree = tree
        self.read = read
        self.batch = batch

    def list_pages(self):
        with self.lock:
            self.sync()
            root = self.read('_index.md')
            return {**self.tree(), 'root': {key: root[key] for key in ('path', 'title', 'revision')}}

    def read_page(self, path):
        with self.lock:
            self.sync()
            return self.read(path)

    def search(self, query, limit=20):
        if not isinstance(query, str) or not query.strip() or len(query) > 500:
            raise HTTPException(422, 'Search query must contain 1 to 500 characters')
        if type(limit) is not int or not 1 <= limit <= 50:
            raise HTTPException(422, 'Limit must be between 1 and 50')
        terms = query.casefold().split()
        with self.lock:
            self.sync()
            def paths(nodes):
                for node in nodes:
                    yield node['page_path']
                    yield from paths(node['children'])
            results = []
            for path in ['_index.md', *paths(self.tree()['nodes'])]:
                page = self.read(path)
                text = (page['title'] + '\n' + page['body']).casefold()
                if not all(term in text for term in terms):
                    continue
                start = max(0, page['body'].casefold().find(terms[0]) - 80)
                results.append({key: page[key] for key in ('path', 'title', 'revision')} | {'excerpt': page['body'][start:start + 400]})
                if len(results) >= limit:
                    break
            return {'results': results, 'limit': limit}

    def publish(self, data, actor):
        request = SimpleNamespace(state=SimpleNamespace(auth={'user': actor}))
        return self.batch(data, request)

    def create_page(self, section, slug, title, body, actor):
        return self.publish({'pages': [{'section': section, 'slug': slug, 'title': title, 'body': body}]}, actor)

    def update_page(self, path, revision, title, body, actor):
        return self.publish({'pages': [{'path': path, 'revision': revision, 'title': title, 'body': body}]}, actor)

    def delete_page(self, path, tree_revision, actor):
        if not isinstance(path, str) or not path.endswith('.md') or path.rsplit('/', 1)[-1] in ('_index.md', 'index.md'):
            raise HTTPException(422, 'Only individual Markdown pages can be deleted through MCP')
        return self.publish({'operations': [{'type': 'delete', 'source': path}], 'tree_revision': tree_revision}, actor)
