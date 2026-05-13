import os


database_url = os.environ["DATABASE_URL"]
print(database_url.replace("postgres://", "postgresql://"))
