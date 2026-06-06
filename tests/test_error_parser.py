"""Basic tests for GhostFix error parser."""
import pytest
from ghostfix.core.error_parser import ErrorParser


@pytest.fixture
def parser():
    return ErrorParser()


def test_detect_python(parser):
    text = """Traceback (most recent call last):
  File "app.py", line 42, in get_user
    return user.profile.name
AttributeError: 'NoneType' object has no attribute 'profile'"""
    assert parser.detect_language(text) == "python"


def test_detect_nodejs(parser):
    text = """TypeError: Cannot read properties of undefined (reading 'id')
    at getUserById (src/routes/user.js:34:20)
    at Layer.handle_request (express/lib/router/layer.js:95:5)"""
    assert parser.detect_language(text) == "nodejs"


def test_parse_python_error(parser):
    text = """Traceback (most recent call last):
  File "app/views.py", line 67, in get_profile
    return request.user.profile.name
AttributeError: 'NoneType' object has no attribute 'profile'"""
    parsed = parser.parse(text)
    assert parsed.language == "python"
    assert parsed.error_type == "AttributeError"
    assert parsed.file_path == "app/views.py"
    assert parsed.line_number == 67


def test_parse_nodejs_error(parser):
    text = """TypeError: Cannot read properties of undefined (reading 'id')
    at getUserById (src/routes/user.js:34:20)"""
    parsed = parser.parse(text)
    assert parsed.language == "nodejs"
    assert parsed.error_type == "TypeError"
    assert "user.js" in parsed.file_path
    assert parsed.line_number == 34


def test_error_signal(parser):
    assert parser.is_error_signal("Traceback (most recent call last):")
    assert parser.is_error_signal("TypeError: something went wrong")
    assert parser.is_error_signal("panic: runtime error: index out of range")
    assert not parser.is_error_signal("Server started on port 3000")
    assert not parser.is_error_signal("GET /api/users 200")
