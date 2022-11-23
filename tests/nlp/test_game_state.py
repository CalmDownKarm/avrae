import os
import gzip
import json
import logging
from pymongo import MongoClient
from typing import Iterable
from pathlib import Path, PosixPath

def ghetto_logger(string_to_log):
    with open("/opt/logfile", "a") as f:
        f.write(f"\n{string_to_log}")



logging.basicConfig(filename="/opt/logfile",
                    filemode='a',
                    format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                    datefmt='%H:%M:%S',
                    level=logging.DEBUG)


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

def find_players(events: Iterable[dict]) -> Iterable[dict]:
    filtered_events =  filter(lambda event: True if event["event_type"] in ("command", "automation_run") and event.get("command_name", "")== "init join" else False, events)  
    for event in filtered_events:
        yield event.get("caster", {})

def dump_players_to_mongo(casters: Iterable[dict]) -> None:
    # establish mongo connection
    collection = "characters"
    for caster in casters:
        if caster:
            primary_key = {field: caster[field] for field in ["owner", "upstream"]}
            mongo_db[collection].update_one(primary_key, {"$set": caster}, upsert=True)

def find_combat_state_updates(events: Iterable[dict]) -> Iterable[dict]:
    filtered_events =  filter(lambda event: True if event["event_type"] == "combat_state_update" else False, events)
    for event in filtered_events:
        yield event.get("data", {})

def dump_csu_to_mongo(state_updates: Iterable[dict])-> None:
    collection = "combats"
    TEST_CHANNEL_ID = 314159265358979323  # pi

    for state_update in state_updates:
        if state_update:
            state_update["channel"] = TEST_CHANNEL_ID
            mongo_db[collection].update_one({"channel": TEST_CHANNEL_ID}, {"$set": state_update}, upsert=True)

def test_combat_state_updates():
    combat_state_updates = find_combat_state_updates(combat_dir_iterator("/opt/dataset"))
    assert len(list(combat_state_updates)) > 0
    dump_csu_to_mongo(combat_state_updates)
    collections = list(mongo_db.list_collection_names())
    assert "combats" in collections
    ghetto_logger(mongo_db['combats'].find({}).limit(5))



def test_can_reach_dataset():
    players = find_players(combat_dir_iterator("/opt/dataset"))
    assert len(list(players)) > 0

def test_write_players_to_mongo() -> None:
    players = find_players(combat_dir_iterator("/opt/dataset"))
    dump_players_to_mongo(players)
    collections = list(mongo_db.list_collection_names())
    assert len(collections) > 0
    assert "characters" in collections
    

def test_avrae_command(avrae, dhttp):
    combat_dir = combat_dir_iterator("/opt/dataset")
    players = find_players(combat_dir)
    dump_players_to_mongo(players)
    combat_state_updates = find_combat_state_updates(combat_dir)
    dump_csu_to_mongo(combat_state_updates)
    avrae.message("!a mo1")
    dhttp.drain()

