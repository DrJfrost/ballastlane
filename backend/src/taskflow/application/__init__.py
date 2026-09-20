"""Application layer: use cases that orchestrate the domain.

Depends on ``domain`` only. Everything else it needs -- persistence, hashing,
tokens, time, messaging -- arrives through the Protocols in ``ports``.
"""
