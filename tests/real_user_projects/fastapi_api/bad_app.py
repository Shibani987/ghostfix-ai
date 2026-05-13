"""Bad ASGI app fixture: uvicorn can import the module, then startup fails."""

from __future__ import annotations

try:
    from fastapi import FastAPI
except ModuleNotFoundError:
    class FastAPI:
        def on_event(self, _event):
            def decorator(func):
                return func

            return decorator


app = FastAPI()


@app.on_event("startup")
def startup() -> None:
    raise RuntimeError("FastAPI startup failed while connecting to cache")


if __name__ == "__main__":
    startup()
