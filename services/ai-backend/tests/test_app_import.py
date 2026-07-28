"""Smoke tests for application startup imports."""

import unittest


class AppImportTest(unittest.TestCase):
    def test_app_main_imports(self) -> None:
        """The ASGI application should be importable by Uvicorn."""
        from app.main import app

        paths = {route.path for route in app.routes}
        self.assertIn("/api/translations/contextual", paths)
