"""C5 reference authority: local SQLite transactions only; no real auth/network endpoint."""
from .store import AuthorityStore, Principal, AuthorityFailure
__all__ = ['AuthorityStore', 'Principal', 'AuthorityFailure']
