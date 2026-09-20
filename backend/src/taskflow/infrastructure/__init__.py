"""Infrastructure layer: adapters for the application ports.

Everything replaceable lives here -- SQLAlchemy, bcrypt, PyJWT, Celery. No
module in ``domain`` or ``application`` imports from this package.
"""
