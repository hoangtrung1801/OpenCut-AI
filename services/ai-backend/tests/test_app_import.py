"""Smoke tests for application startup imports."""

import unittest


class AppImportTest(unittest.TestCase):
    def test_app_main_imports(self) -> None:
        """The ASGI application should be importable by Uvicorn."""
        import app.main  # noqa: F401
