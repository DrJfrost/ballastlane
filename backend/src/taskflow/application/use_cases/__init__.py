"""Use cases: one class per business operation.

Each exposes a single ``execute`` method, takes its collaborators through the
constructor, and returns a DTO. That uniform shape is what makes the wiring
in ``presentation/dependencies`` mechanical and the tests boring.
"""
