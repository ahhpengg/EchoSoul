"""Pytest root conftest.

Its presence puts the repository root on ``sys.path`` (pytest prepend import
mode), so tests can ``import src...`` when run with a bare ``pytest`` from the
project root.
"""
