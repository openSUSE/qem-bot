from logging import getLogger
from typing import Dict, List

import requests

from ..errors import EmptyChannels, EmptyPackagesError, NoRepoFoundError
from ..types.incident import Incident

logger = getLogger("bot.loader.qem")


def get_incidents(token: Dict[str, str]) -> List[Incident]:
    incidents = requests.get(
        "http://dashboard.qam.suse.de/api/incidents", headers=token
    ).json()

    xs = []
    for i in incidents:
        try:
            xs.append(Incident(i))
        except NoRepoFoundError as e:
            logger.info(
                "Project %s can't calculate repohash %s .. skipping" % (i["project"], e)
            )
        except EmptyChannels as e:
            logger.info("Project %s has empty channels" % i["project"])
        except EmptyPackagesError as e:
            logger.info("Project %s has empty packages" % i["project"])

    return xs
