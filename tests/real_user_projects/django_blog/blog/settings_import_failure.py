from blog.local_settings import DATABASE_URL

SECRET_KEY = "local-fixture-only"
DATABASES = {"default": DATABASE_URL}
