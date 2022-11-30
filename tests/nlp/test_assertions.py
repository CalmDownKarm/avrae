import os
import json
import openai
from typing import Iterable
from pymongo import MongoClient

from pathlib import Path

dir_path = Path(__file__).parent

mongodb_url = os.getenv("MONGO_URL")
mongo_client = MongoClient(mongodb_url)
mongo_db = mongo_client.avrae

# with open("./openai_key.txt") as f:
#     openai.api_key = f.read()
# os.environ["OPENAI_API_KEY"] = openai.api_key
from tests.utils import active_combat


def assert_firebolt(active_combat):
    assert hp_change(active_combat, "GO1", 7, "DAMAGE")


def assert_fireball(active_combat):
    orcs = {"OR1": 13, "OR2": 9, "OR3": 2}
    for orc, init_hp in orcs.items():
        assert hp_change(active_combat, orc, init_hp, "DAMAGE")


async def assert_bardic_inspiration(active_combat):
    effects = (await active_combat).get_combatant("Noxxis Blazehammer").get_effects()
    assert len(effects) == 1
    assert effects[0].name == "Feeling Inspired"


async def assert_bless(active_combat):
    for combatant in ("Reef", "Calti", "Ophiz"):
        effects = (await active_combat).get_combatant(combatant).get_effects()
        assert len(effects) == 1
        assert effects[0].named == "Blessed"


async def assert_healing(active_combat):
    assert hp_change(active_combat, "Reef", 20, "HEALING")
    assert hp_change(active_combat, "Calti", 20, "NOOP")


async def hp_change(active_combat, combatant, initial_hp, change_type="DAMAGE"):
    current_hp = (await active_combat).get_combatant(combatant).hp
    if change_type == "DAMAGE":
        return current_hp < initial_hp
    if change_type == "HEALING":
        return current_hp > initial_hp
    if change_type == "NOOP":
        return current_hp == initial_hp


async def melee_attack(active_combat):
    assert hp_change(active_combat, "GFoY1", 53)


async def monster_attack(active_combat):
    assert hp_change(active_combat, "Calti", 40, "DAMAGE")
    assert hp_change(active_combat, "Noxxis Blazehammer", 55, "NOOP")


scenarios = {"fireball": assert_fireball, "bardic_inspiration": assert_bardic_inspiration}


def dump_players_to_mongo(casters: Iterable[dict]) -> None:
    # establish mongo connection
    collection = "characters"
    for caster in casters:
        if caster:
            primary_key = {field: caster[field] for field in ["owner", "upstream"]}
            mongo_db[collection].update_one(primary_key, {"$set": caster}, upsert=True)


def dump_csu_to_mongo(state_updates: Iterable[dict]) -> None:
    collection = "combats"
    TEST_CHANNEL_ID = 314159265358979323  # pi

    for state_update in state_updates:
        if state_update:
            state_update["channel"] = TEST_CHANNEL_ID
            mongo_db[collection].update_one({"channel": TEST_CHANNEL_ID}, {"$set": state_update}, upsert=True)


def predict(prompt, gpt_kwargs):
    """Make call to gpt3"""
    if gpt_kwargs.get("model", None) is not None:
        gpt_kwargs["prompt"] = prompt
        response = openai.Completion.create(**gpt_kwargs)
        return response["choices"][0]["text"]


async def test_all_assertions(avrae, dhttp):
    with open(dir_path / "unit_test_scenarios.jsonl") as f:
        scenarios = [json.loads(line) for line in f.readlines()]
    gpt_kwargs = {"model": "davinci", "temperature": 0.7}
    for scenario in scenarios:
        characters = scenario["characters"]
        scenario_name = scenario["scenario"]
        combat = scenario["combat"]
        ## dump characters and combats into db
        dump_players_to_mongo(characters)
        dump_csu_to_mongo([combat])

        prompt = scenario["prompt"]
        response = scenario["command"]
        # response = predict(prompt, gpt_kwargs)
        combat = await active_combat(avrae)
        avrae.message(f"{response} hit fail", author_id=combat.current_combatant.controller_id)
        await dhttp.drain()
        scenarios[scenario_name](await active_combat(avrae))
