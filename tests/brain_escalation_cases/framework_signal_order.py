class FrameworkSignalOrderError(Exception):
    pass


class AppRegistry:
    ready = False


def on_startup():
    if not AppRegistry.ready:
        raise FrameworkSignalOrderError("startup signal fired before application registry was ready")


def boot_framework():
    on_startup()
    AppRegistry.ready = True


boot_framework()
