from abc import ABCMeta, abstractmethod, abstractstaticmethod
from typing import Any, Dict, List

from .incident import Incident


class BaseConf(metaclass=ABCMeta):
    def __init__(self, product: str, settings, config) -> None:
        self.product = product
        self.settings = settings

    @abstractmethod
    def __call__(
        self, incidents: List[Incident], token: Dict[str, str], ignore_onetime: bool
    ) -> List[Dict[str, Any]]:
        pass

    @abstractstaticmethod
    def normalize_repos(config):
        pass
