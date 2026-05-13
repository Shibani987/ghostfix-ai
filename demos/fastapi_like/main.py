try:
    from fastapi import FastAPI
except Exception:
    class FastAPI:
        pass


app = FastAPI()


def startup():
    raise ModuleNotFoundError("No module named 'missing_api_client'")


if __name__ == "__main__":
    startup()
