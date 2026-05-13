try:
    from fastapi import FastAPI, UploadFile
except ModuleNotFoundError:
    class FastAPI:
        def post(self, _path):
            def decorator(handler):
                return handler

            return decorator

    class UploadFile:
        filename = ""


app = FastAPI()


@app.post("/invoices")
def upload_invoice(file: UploadFile):
    import multipart_parser_for_ghostfix_demo

    return {"filename": file.filename, "parser": multipart_parser_for_ghostfix_demo.__name__}


class UploadedFile:
    filename = "invoice.pdf"


print(upload_invoice(UploadedFile()))
