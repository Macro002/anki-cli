from ankicli.errors import ApiError  # noqa: F401
class Deferred:
    def __init__(self, value=None, error=None):
        self.done, self.value, self.error = True, value, error
def completed(value=None, error=None):
    return Deferred(value, error)
