from logging import getLogger
from pathlib import Path
from typing import List, Union

from ruamel.yaml import YAML  # type: ignore

from ..types.aggregate import Aggregate
from ..types.incidents import Incidents

logger = getLogger("bot.loader.config")


def load_metadata(path: Path, aggregate: bool) -> List[Union[Aggregate, Incidents]]:

    ret = []

    loader = YAML(typ="safe")

    for p in path.glob("*.yml"):

        try:
            data = loader.load(p)
        except Exception as e:
            logger.exception(e)
            continue

        try:
            settings = data.get("settings")
        except AttributeError:
            # not valid yaml for bot settings
            continue

        if "product" not in data:
            logger.error("Missing product in %s" % p)
            continue

        if settings:
            for key in data:
                if key == "incidents":
                    ret.append(Incidents(data["product"], settings, data[key]))
                elif key == "aggregate" and not aggregate:
                    ret.append(Aggregate(data["product"], settings, data[key]))
                else:
                    continue
    return ret
