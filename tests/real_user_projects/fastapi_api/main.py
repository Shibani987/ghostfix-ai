"""FastAPI-like app with intentional import/startup failures."""

from __future__ import annotations

try:
    from fastapi import FastAPI
except ModuleNotFoundError:
    class FastAPI:
        def get(self, _path):
            def decorator(func):
                return func

            return decorator

import missing_payment_gateway


app = FastAPI()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "gateway": missing_payment_gateway.NAME}


if __name__ == "__main__":
    print(health())
