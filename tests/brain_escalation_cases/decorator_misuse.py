class DecoratorBindingError(Exception):
    pass


def require_request(func):
    def wrapper(request, *args, **kwargs):
        if "user" not in request:
            raise DecoratorBindingError("decorated view expected request with user before calling handler")
        return func(request, *args, **kwargs)

    return wrapper


@require_request
def dashboard(request):
    return request["user"]["name"]


print(dashboard({}))
