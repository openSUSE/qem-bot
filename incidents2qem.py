from argparse import ArgumentParser
import sys
from typing import NamedTuple, Sequence

from openqa_client.client import OpenQA_Client as OC
import requests as R


API_INCIDENTS = "http://qam2.suse.de:4000/api/incidents"
API_SETTINGS = "http://qam2.suse.de:4000/api/incident_settings/"

API_PUT = "http://qam2.suse.de:4000/api/jobs"

oqa = OC(server="openqa.suse.de", scheme="https")

class Data(NamedTuple):
    incident: int
    qem_id: int
    flavor: str
    arch: str
    distri: str
    version: str
    build: str


def active_incidents() -> Sequence[int]:
    try:
        data = R.get(API_INCIDENTS, headers=TOKEN).json()
    except Exception as e:
        print(e)
        raise e

    return [i["number"] for i in data]


def incident_settings(number: int) -> Sequence[Data]:
    url = API_SETTINGS + f"{number}"
    print("Getting settings for %s" % number)
    try:
        data = R.get(url, headers=TOKEN).json()
    except Exception as e:
        print(e)
        raise e

    if "error" in data:
        raise ValueError

    ret = []
    for d in data:
        ret.append(
            Data(
                number,
                d["id"],
                d["flavor"],
                d["arch"],
                d["settings"]["DISTRI"],
                d["version"],
                d["settings"]["BUILD"],
            )
        )

    return ret

def get_openqa(data: Data):
    print(f"getting openqa for {data}")
    param = {}
    param["scope"] = "relevant"
    param["latest"] = "1"
    param["flavor"]  = data.flavor
    param["distri"] = data.distri
    param["build"] = data.build
    param["version"] = data.version
    param["arch"] = data.arch

    ret = None
    try:
        ret = oqa.openqa_request("GET", "jobs", param)["jobs"]
    # TODO: correct handling
    except Exception as e:
        print(e)
        raise e
    return ret

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

def normalize_data(data: Data, job):
    ret = {}
    ret["job_id"] = job["id"]
    ret["incident_settings"] = data.qem_id 
    ret["name"] = job["name"]
    ret["distri"] = data.distri
    ret["group_id"] = job["group_id"]
    ret["job_group"] = job["group"]
    ret["version"] = data.version
    ret["arch"] = data.arch
    ret["flavor"] = data.flavor
    ret["status"] = normalize_results(job["result"])
    ret["build"] = data.build
    ret["update_settings"] = None

    return ret

if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("token", type=str)
    args = parser.parse_args(sys.argv[1:])

    global TOKEN
    TOKEN = {"Authorization": f"Token {args.token}"}

    inc = active_incidents()
    incidents = []
    for i in inc:
        try:
            incidents += incident_settings(i)
        except ValueError:
            continue
    full = {}
    for d in incidents:
        full[d] = get_openqa(d)

    results = []
    for key, value in full.items():
        for v in value:
            if not "group" in v:
                continue
            if v["clone_id"]:
                print("Clone job %s" % v["clone_id"])
                continue
            if v["group"].startswith('Test') or v["group"].startswith('Devel'):
                print("Development group -- %s" % v["id"])
            try:
                r = normalize_data(key, v)
            except KeyError:
                continue

            results.append(r)

    for r in results:

        print(f"posting : {r}")
        try:
            x = R.put(API_PUT, headers=TOKEN, json=r)
            if x.status_code != 200:
                print(x.text)
        except Exception as e:
            print(e)
        print(x.status_code)
            
            


