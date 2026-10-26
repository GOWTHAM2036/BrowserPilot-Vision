"""Shared fixtures for BrowserPilot Vision test suite."""

import threading
import time
import pytest
from werkzeug.serving import make_server

from demo_site.app import app as flask_demo_app


@pytest.fixture(scope="session")
def local_demo_server():
    """Run Flask demo site in a background thread for testing."""
    server = make_server("127.0.0.1", 5001, flask_demo_app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.5)  # Allow server to bind
    yield "http://127.0.0.1:5001/"
    server.shutdown()
