"""Repositories: query functions. The only place SQL lives.

Each module here owns the rows it touches and exposes functions that take a
connection/session and return plain data. No SQL string escapes this package.
"""
