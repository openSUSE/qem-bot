from logging import getLogger
from pathlib import Path
from typing import List, Set, Union

from ruamel.yaml import YAML  # type: ignore

from ..types import Data
from ..types.aggregate import Aggregate
from ..types.incidents import Incidents

logger = getLogger("bot.loader.config")


def load_metadata(
    path: Path, aggregate: bool, incidents: bool, extrasettings: Set[str]
) -> List[Union[Aggregate, Incidents]]:

    ret: List[Union[Aggregate, Incidents]] = []

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
                if key == "incidents" and not incidents:
                    ret.append(
                        Incidents(data["product"], settings, data[key], extrasettings)
                    )
                elif key == "aggregate" and not aggregate:
                    ret.append(Aggregate(data["product"], settings, data[key]))
                else:
                    continue
    return ret


def read_products(path: Path) -> List[Data]:
    loader = YAML(typ="safe")
    ret = []

    for p in path.glob("*.yml"):
        data = loader.load(p)

        if not data:
            logger.error("something wrong with %s" % str(p))
            continue
        if not isinstance(data, dict):
            logger.error("something wrong with %s" % str(p))
            continue

        try:
            flavor = data["aggregate"]["FLAVOR"]
        except KeyError:
            logger.info("file %s dont have aggregate" % str(p))
            continue

        try:
            distri = data["settings"]["DISTRI"]
            version = data["settings"]["VERSION"]
            product = data["product"]
        except Exception as e:
            logger.exception(e)
            continue

        for arch in data["aggregate"]["archs"]:
            ret.append(Data(0, 0, flavor, arch, distri, version, "", product))

    return ret


def get_onearch(pth: Path) -> Set[str]:
    loader = YAML(typ="safe")

    try:
        data = loader.load(pth)
    except Exception as e:
        logger.exception(e)
        return set()

    return set(data)
