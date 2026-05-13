from core.training_memory import save_training_data
import random
import hashlib

PACKAGES = [
    "numpy", "pandas", "matplotlib", "requests", "flask", "django",
    "fastapi", "uvicorn", "pydantic", "sqlalchemy", "sklearn",
    "torch", "tensorflow", "opencv-python", "bs4", "python-dotenv",
    "python-multipart", "pydantic-settings", "psycopg2", "pymongo"
]

VARIABLES = ["x", "data", "result", "response", "user", "items", "config", "token", "df", "model"]
FILES = ["data.csv", "config.json", "settings.py", "app.log", "model.pkl", "users.json", "db.sqlite3", "main.py"]
KEYS = ["name", "age", "id", "email", "token", "password", "status", "items", "headers"]
ATTRS = ["append", "read", "write", "json", "split", "get", "lower", "upper", "shape", "predict"]
TYPES = ["int", "str", "list", "dict", "NoneType", "float", "DataFrame"]
VALUES = ["abc", "12a", "xyz", "hello", "3.4.5", "None", ""]
OBJECTS = ["list", "dict", "str", "int", "NoneType", "Response", "DataFrame", "Series"]

ERROR_TEMPLATES = [
    ("ModuleNotFoundError", "ModuleNotFoundError: No module named '{pkg}'",
     "The required Python package is not installed in the active environment.",
     "pip install {pkg}"),

    ("NameError", "NameError: name '{var}' is not defined",
     "A variable or function is used before being defined.",
     "Define '{var}' before using it or fix the spelling."),

    ("TypeError", "TypeError: unsupported operand type(s) for +: '{t1}' and '{t2}'",
     "An operation is being performed between incompatible data types.",
     "Convert values to compatible types before using this operation."),

    ("TypeError", "TypeError: '{obj}' object is not callable",
     "The code is trying to call an object like a function.",
     "Check whether '{obj}' is actually a function before calling it."),

    ("ValueError", "ValueError: invalid literal for int() with base 10: '{val}'",
     "A value cannot be converted to integer.",
     "Validate or clean the input before conversion."),

    ("FileNotFoundError", "FileNotFoundError: No such file or directory: '{file}'",
     "The file path is wrong or the file does not exist.",
     "Check the file path and ensure the file exists."),

    ("KeyError", "KeyError: '{key}'",
     "The dictionary key does not exist.",
     "Use dict.get() or check whether the key exists before accessing it."),

    ("IndexError", "IndexError: list index out of range",
     "The code is accessing an index outside the list length.",
     "Check list length before indexing."),

    ("AttributeError", "AttributeError: '{obj}' object has no attribute '{attr}'",
     "The object does not support the requested attribute or method.",
     "Check the object type and use a valid attribute or method."),

    ("ZeroDivisionError", "ZeroDivisionError: division by zero",
     "The code is dividing by zero.",
     "Check denominator value before division."),

    ("IndentationError", "IndentationError: expected an indented block",
     "Python expects indentation after a block statement.",
     "Fix indentation after if, for, while, def, or class."),

    ("SyntaxError", "SyntaxError: '(' was never closed",
     "There is an unclosed bracket or parenthesis.",
     "Close the missing bracket or parenthesis."),

    ("SyntaxError", "SyntaxError: invalid syntax",
     "The Python syntax is invalid near the reported line.",
     "Check punctuation, brackets, colons, and statement structure."),

    ("PermissionError", "PermissionError: [Errno 13] Permission denied: '{file}'",
     "The program does not have permission to access the file.",
     "Run with proper permissions or change file access rights."),

    ("JSONDecodeError", "json.decoder.JSONDecodeError: Expecting value: line 1 column 1",
     "The response or file is not valid JSON.",
     "Check the response body or JSON file before parsing."),

    ("ConnectionError", "requests.exceptions.ConnectionError: Failed to establish a new connection",
     "The app cannot connect to the remote server.",
     "Check internet connection, API URL, or server availability."),

    ("TimeoutError", "TimeoutError: request timed out",
     "The request took too long to complete.",
     "Increase timeout or check server/network performance."),

    ("SSLError", "requests.exceptions.SSLError: certificate verify failed",
     "SSL certificate verification failed.",
     "Check certificate validity or configure trusted certificates."),

    ("HTTPError", "requests.exceptions.HTTPError: 404 Client Error: Not Found for url",
     "The requested API endpoint was not found.",
     "Check the API URL, route, and request method."),

    ("ImproperlyConfigured", "django.core.exceptions.ImproperlyConfigured: Requested setting DATABASES, but settings are not configured",
     "Django settings are not loaded properly.",
     "Set DJANGO_SETTINGS_MODULE or run through manage.py."),

    ("OperationalError", "django.db.utils.OperationalError: no such table: auth_user",
     "Database migrations are not applied.",
     "Run python manage.py migrate."),

    ("TemplateDoesNotExist", "django.template.exceptions.TemplateDoesNotExist: index.html",
     "Django cannot find the template file.",
     "Check template directory and template name."),

    ("NoReverseMatch", "django.urls.exceptions.NoReverseMatch: Reverse for 'home' not found",
     "URL name is missing or incorrect.",
     "Check urls.py and template url tag name."),

    ("DisallowedHost", "django.core.exceptions.DisallowedHost: Invalid HTTP_HOST header",
     "The host is not allowed in Django settings.",
     "Add the host to ALLOWED_HOSTS in settings.py."),

    ("ValidationError", "pydantic.error_wrappers.ValidationError: field required",
     "Required input field is missing.",
     "Provide all required fields or set default values."),

    ("RuntimeError", "RuntimeError: Form data requires python-multipart to be installed",
     "FastAPI file/form upload dependency is missing.",
     "pip install python-multipart"),

    ("ImportError", "ImportError: cannot import name 'BaseSettings' from 'pydantic'",
     "Pydantic v2 moved BaseSettings to pydantic-settings.",
     "pip install pydantic-settings and import BaseSettings from pydantic_settings."),

    ("UvicornError", "Error loading ASGI app. Could not import module 'main'",
     "Uvicorn cannot find or import the ASGI app module.",
     "Check module path and run uvicorn main:app from the correct directory."),

    ("RuntimeError", "RuntimeError: Working outside of application context",
     "Flask code is running outside the app context.",
     "Use app.app_context() or move code inside a request/app context."),

    ("ImportError", "ImportError: cannot import name 'app' from 'app'",
     "Flask app import path is incorrect or circular import exists.",
     "Check app object name and avoid circular imports."),

    ("OperationalError", "sqlalchemy.exc.OperationalError: could not connect to server",
     "Database server is unavailable or connection config is wrong.",
     "Check database URL, host, port, credentials, and server status."),

    ("IntegrityError", "sqlalchemy.exc.IntegrityError: duplicate key value violates unique constraint",
     "The database insert violates a unique constraint.",
     "Check duplicate values before inserting."),

    ("ProgrammingError", "psycopg2.errors.UndefinedTable: relation does not exist",
     "The database table does not exist.",
     "Create the table or run migrations."),

    ("PipError", "pip: command not found",
     "pip is not available in the current environment.",
     "Install pip or use python -m pip."),

    ("VenvError", "ModuleNotFoundError: No module named '{pkg}' after installation",
     "Package may be installed in a different Python environment.",
     "Activate the correct virtual environment and reinstall the package."),

    ("VersionConflict", "ImportError: version conflict for package '{pkg}'",
     "Installed package version is incompatible.",
     "Upgrade, downgrade, or pin a compatible package version."),

    ("DotEnvError", "ValueError: SUPABASE_URL or SUPABASE_KEY missing in .env",
     "Environment variables are missing or .env was not loaded.",
     "Check .env path, variable names, and python-dotenv loading."),

    ("PandasError", "pandas.errors.ParserError: Error tokenizing data",
     "CSV file format is invalid or inconsistent.",
     "Check CSV delimiter, quotes, and malformed rows."),

    ("ShapeError", "ValueError: Found input variables with inconsistent numbers of samples",
     "ML input features and labels have different lengths.",
     "Ensure X and y have the same number of samples."),

    ("TorchError", "RuntimeError: CUDA out of memory",
     "The model requires more GPU memory than available.",
     "Reduce batch size, use CPU, or use a smaller model."),

    ("OpenCVError", "cv2.error: OpenCV could not read image",
     "Image path is wrong or file format is unsupported.",
     "Check image path and file format."),
]


def values_map():
    return {
        "pkg": random.choice(PACKAGES),
        "var": random.choice(VARIABLES),
        "file": random.choice(FILES),
        "key": random.choice(KEYS),
        "attr": random.choice(ATTRS),
        "t1": random.choice(TYPES),
        "t2": random.choice(TYPES),
        "val": random.choice(VALUES),
        "obj": random.choice(OBJECTS),
    }


def make_context(error_type: str, vm: dict) -> str:
    contexts = [
        f"Python CLI script failed with {error_type}.",
        f"Backend server startup failed with {error_type}.",
        f"Django/FastAPI/Flask local development error: {error_type}.",
        f"Runtime failure during local development. Related package: {vm['pkg']}.",
        f"Developer ran code from terminal and got {error_type}.",
        f"Error occurred while reading file {vm['file']}.",
        f"Possible variable involved: {vm['var']}.",
    ]
    return random.choice(contexts)


def fingerprint(error: str, cause: str, fix: str, context: str) -> str:
    raw = f"{error}|{cause}|{fix}|{context}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_row():
    error_type, template, cause, fix = random.choice(ERROR_TEMPLATES)
    vm = values_map()

    error_text = template.format(**vm)
    fix_text = fix.format(**vm)
    context = make_context(error_type, vm)

    return {
        "error": error_text,
        "error_type": error_type,
        "message": error_text,
        "cause": cause,
        "fix": fix_text,
        "source": "synthetic_realistic_v3",
        "language": "python",
        "context": context,
        "success": True,
        "fingerprint": fingerprint(error_text, cause, fix_text, context),
    }


def seed_dataset(n=10000):
    seen = set()
    inserted = 0
    attempts = 0
    max_attempts = n * 30

    while inserted < n and attempts < max_attempts:
        attempts += 1
        row = generate_row()

        if row["fingerprint"] in seen:
            continue

        seen.add(row["fingerprint"])

        try:
            save_training_data(row)
            inserted += 1
        except Exception as e:
            print(f"Skipped row: {str(e)[:120]}")

        if inserted > 0 and inserted % 500 == 0:
            print(f"{inserted}/{n} inserted...")

    print(f"{inserted}/{n} training dataset inserted ✅")

    if inserted < n:
        print("⚠️ Not enough unique rows. Add more templates/lists.")


if __name__ == "__main__":
    seed_dataset(10000)
