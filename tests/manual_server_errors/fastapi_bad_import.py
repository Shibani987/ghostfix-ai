"""Minimal FastAPI app with an intentionally bad startup import."""

from fastapi import FastAPI

from tests.manual_server_errors.missing_api_client import Client


app = FastAPI()


@app.get("/")
def read_root():
    return {"client": Client.__name__}
