import os
import gzip
import json
import logging
from pymongo import MongoClient
from typing import Iterable
from pathlib import Path, PosixPath

log = logging.getLogger(__name__)
mongodb_url = os.getenv("MONGO_URL")
mongo_client = MongoClient(mongodb_url)
mongo_db = mongo_client.avrae

def read_gzipped_file(fp: PosixPath) -> Iterable[dict]:
    """Given a path to a gzipped data file, return an iterator of events in the file."""
    try:
        with gzip.open(fp, mode="r") as f:
            for line in f:
                yield json.loads(line)
    except gzip.BadGzipFile as e:
        print(f"Could not read {fp}")

def combat_dir_iterator(dirpath: str) -> Iterable[dict]:
    dirpath = Path(dirpath)
    """Given a path to a directory of gzipped combat event files, return an iterator of events in the dir."""
    for fp in sorted(dirpath.glob("**/*.gz")):
            yield from read_gzipped_file(fp)

def find_players(events_generator: Iterable[dict]) -> Iterable[dict]:
    events =  filter(lambda event: True if event["event_type"] == "command" and event["command_name"]== "init join" else False, events_generator)
    for event in events:
        yield event["caster"]

def dump_players_to_mongo(casters: Iterable[dict]) -> None:
    # establish mongo connection
    collection = "characters"
    for caster in casters:
        primary_key = {field: caster[field] for field in ["owner", "upstream"]}
        mongo_db[collection].update_one(primary_key, {"$set": caster}, upsert=True)

def test_can_reach_dataset():
    players = find_players(combat_dir_iterator("/opt/dataset"))
    players = list(players)
    assert len(players) > 0

def test_write_players_to_mongo() -> None:
    players = find_players(combat_dir_iterator("/opt/dataset"))
    dump_players_to_mongo(players)
    collections = list(mongo_db.list_collection_names())
    log.info(collections)
    assert len(collections) > 0

