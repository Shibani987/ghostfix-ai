import json

data = ""
if data:
    result = json.loads(data)
else:
    result = None
    print("GhostFix: Empty JSON input")
print(result)
