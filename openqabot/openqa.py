import logging
from pprint import pformat

from openqa_client.client import OpenQA_Client

logger = logging.getLogger("bot.openqa")


class openQAInterface:
    def __init__(self):
        self.openqa = OpenQA_Client(server="openqa.suse.de", scheme="https")

    def post_job(self, settings):
        logger.info("Openqa isos POST {}".format(pformat(settings)))
        try:
            self.openqa.openqa_request("POST", "isos", data=settings, retries=3)
        except Exception as e:
            logger.exception(e)
            logger.error("Post failed with {}".format(pformat(settings)))
