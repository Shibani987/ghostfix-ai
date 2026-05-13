import json


class Response:
    status_code = 204
    text = ""


response = Response()
payload = json.loads(response.text)
print(payload["id"])
