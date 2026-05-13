SECRET_KEY = "local-fixture-only"
ROOT_URLCONF = "blog.urls"
INSTALLED_APPS = [
    "blog.posts",
    "blog.comments_missing",
]
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": ["templates"],
        "APP_DIRS": True,
    }
]
