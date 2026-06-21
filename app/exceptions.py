import falcon


class BusinessError(Exception):
    def __init__(self, title: str, description: str, code: int = 400):
        self.title = title
        self.description = description
        self.code = code
        super().__init__(f"{title}: {description}")

    def to_http(self):
        if self.code == 404:
            return falcon.HTTPNotFound(title=self.title, description=self.description)
        elif self.code == 401:
            return falcon.HTTPUnauthorized(title=self.title, description=self.description)
        elif self.code == 403:
            return falcon.HTTPForbidden(title=self.title, description=self.description)
        else:
            return falcon.HTTPBadRequest(title=self.title, description=self.description)


class ValidationError(BusinessError):
    def __init__(self, description: str, title: str = "参数错误"):
        super().__init__(title=title, description=description, code=400)


class NotFoundError(BusinessError):
    def __init__(self, description: str, title: str = "未找到"):
        super().__init__(title=title, description=description, code=404)


class StateConflictError(BusinessError):
    def __init__(self, description: str, title: str = "状态冲突"):
        super().__init__(title=title, description=description, code=400)


class BlacklistBlockedError(BusinessError):
    def __init__(self, description: str, scene: str = "操作"):
        super().__init__(title=f"{scene}失败", description=description, code=400)


class BlacklistGrayError(BusinessError):
    def __init__(self, description: str, scene: str = "操作"):
        super().__init__(title=f"需要二次校验", description=description, code=400)


class PenaltyBlockedError(BusinessError):
    def __init__(self, description: str, scene: str = "操作"):
        super().__init__(title=f"{scene}失败", description=description, code=400)
