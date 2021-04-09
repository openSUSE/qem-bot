#!/esr/bin/python3

from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path
import sys
from typing import List, NamedTuple

from openqa_client.client import OpenQA_Client as O
import requests as R
from ruamel.yaml import YAML  # type: ignore

oqa = O(server="openqa.suse.de")

API = "http://qam2.suse.de:4000/api/update_settings"
API2 = "http://qam2.suse.de:4000/api/jobs"


class Data(NamedTuple):
    product: str
    distri: str
    flavor: str
    version: str
    arch: str
    build: str = ""
    updates_settings: int = 0


def get_jobs(data: Data):

    values = {
        "distri": data.distri,
        "version": data.version,
        "arch": data.arch,
        "flavor": data.flavor,
        "scope": "relevant",
        "latest": "1",
        "build": data.build,
    }

    # TODO: exceptions
    print(f"Getting job for {values}")
    jobs = oqa.openqa_request("GET", "jobs", values)["jobs"]

    return jobs


def normalize_results(result: str) -> str:
    if result in ("passed", "softfailed"):
        return "passed"
    if result == "none":
        return "waiting"
    if result in (
        "timeout_exceeded",
        "incomplete",
        "obsoleted",
        "parallel_failed",
        "skipped",
        "parallel_restarted",
        "user_cancelled",
        "user_restarted",
    ):
        return "stopped"
    if result == "failed":
        return "failed"

    return "failed"


def read_configs(configs: Path) -> List[Data]:
    loader = YAML(typ="safe")
    ret = []

    for p in configs.glob("*.yml"):
        data = loader.load(p)
        if not data:
            print(f"{p}")
        try:
            flavor = data["aggregate"]["FLAVOR"]
        except KeyError:
            print(f"file {p} dont have aggregate")
            continue
        print(p)
        try:
            distri = data["settings"]["DISTRI"]
            version = data["settings"]["VERSION"]
            product = data["product"]
        except Exception:
            import pdb; pdb.set_trace()
        for arch in data["aggregate"]["archs"]:

            ret.append(Data(product, distri, flavor, version, arch))

    return ret


@lru_cache(maxsize=256)
def get_update_settingsd(data: Data):
    url = API + f"?product={data.product}&arch={data.arch}"
    settings = R.get(url, headers=TOKEN).json()

    ret = []
    if not settings:
        raise KeyError

    print(f"Getting id for {data}")
    # use last three shedule
    for s in settings[:3]:
        ret.append(
            Data(
                data.product,
                data.distri,
                data.flavor,
                data.version,
                data.arch,
                s["build"],
                s["id"],
            )
        )

    return ret


def normalize_data(data: Data, job):
    ret = {}
    ret["job_id"] = job["id"]
    ret["incident_settings"] = None
    ret["name"] = job["name"]
    ret["distri"] = data.distri
    ret["group_id"] = job["group_id"]
    ret["job_group"] = job["group"]
    ret["version"] = data.version
    ret["arch"] = data.arch
    ret["flavor"] = data.flavor
    ret["status"] = normalize_results(job["result"])
    ret["build"] = data.build
    ret["update_settings"] = data.updates_settings

    return ret


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("token", type=str)
    parser.add_argument(
        "-c", "--configs", type=Path, help="Path to configs directory", required=True
    )

    args = parser.parse_args(sys.argv[1:])

    global TOKEN
    TOKEN = {"Authorization": f"Token {args.token}"}

    data = read_configs(args.configs)
    updates_settings = []

    for d in data:
        updates_settings += get_update_settingsd(d)

    del data

    job_results = {}
    with ThreadPoolExecutor() as executor:
        future_j = {executor.submit(get_jobs, f): f for f in updates_settings}
        for future in as_completed(future_j):
            job_results[future_j[future]] = future.result()

    results = []
    for key, values in job_results.items():
        for v in values:
            if not "group" in v:
                continue
            if v["clone_id"]:
                print("Clone job %s" % v["clone_id"])
                continue
            if v["group"].startswith("Test") or v["group"].startswith("Devel"):
                print("Development group -- %s" % v["id"])
                continue
            try:
                r = normalize_data(key, v)
            except KeyError:
                continue

            results.append(r)

    for r in results:

        print(f"posting : {r}")
        try:
            x = R.put(API2, headers=TOKEN, json=r)
            if x.status_code != 200:
                print(x.text)
        except Exception as e:
            print(e)
        print(x.status_code)
