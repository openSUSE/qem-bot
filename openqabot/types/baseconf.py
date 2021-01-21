from abc import abstractmethod, abstractstaticmethod
from abc import ABCMeta
from typing import List


class BaseConf(metaclass=ABCMeta):
    def __init__(self, product: str, settings, config) -> None:
        self.product = product
        self.settings = settings

    @abstractmethod
    def __call__(self, *args, **kwargs):
        pass

    @abstractstaticmethod
    def normalize_repos(config):
        pass

