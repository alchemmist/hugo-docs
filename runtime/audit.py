from contextvars import ContextVar

from fastapi import Request

CURRENT_ACTOR = ContextVar('wiki_actor', default=None)


async def actor_context(request: Request):
    session = getattr(request.state, 'auth', None)
    token = CURRENT_ACTOR.set(session['user'] if session else None)
    try:
        yield
    finally:
        CURRENT_ACTOR.reset(token)
