from app.logger import ServiceLogger


class BaseService:
    def __init__(self):
        self.log = ServiceLogger(self.__class__.__name__)
