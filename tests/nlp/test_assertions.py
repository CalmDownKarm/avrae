import os
import json
import openai
from typing import Iterable
from pymongo import MongoClient
from nltk.translate.gleu_score import sentence_gleu
from rouge_score import rouge_scorer
from pathlib import Path
import pandas as pd
from cogs5e.initiative.combat import Combat
from cogs5e.models.character import Character
dir_path = Path(__file__).parent

mongodb_url = os.getenv("MONGO_URL")
mongo_client = MongoClient(mongodb_url)
mongo_db = mongo_client.avrae


def ghetto_logger(string_to_log):
    with open("/opt/logfile", "a") as f:
        f.write(f"\n{string_to_log}")


# with open("./openai_key.txt") as f:
#     openai.api_key = f.read()
# os.environ["OPENAI_API_KEY"] = openai.api_key
from tests.utils import active_combat, requires_data


def hp_change(active_combat, combatant, initial_hp, change_type="DAMAGE"):
    current_hp = active_combat.get_combatant(combatant).hp
    if change_type == "DAMAGE":
        return current_hp < initial_hp
    if change_type == "HEALING":
        return current_hp > initial_hp
    if change_type == "NOOP":
        return current_hp == initial_hp


def assert_firebolt(active_combat):
    return hp_change(active_combat, "GO1", 7, "DAMAGE")


def assert_fireball(active_combat):
    orcs = {"OR1": 13, "OR2": 9, "OR3": 2}
    return all([hp_change(active_combat, orc, init_hp, "DAMAGE") for orc, init_hp in orcs.items()])


def assert_bardic_inspiration(active_combat):
    effects = active_combat.get_combatant("Noxxis Blazehammer").get_effects()
    return len(effects) == 1 and effects[0].name.startswith("Feeling Inspired")


def assert_bless(active_combat):
    for combatant in ("Reef", "Calti", "Ophiz"):
        effects = active_combat.get_combatant(combatant).get_effects()
        return len(effects) == 1 and effects[0].name == "Blessed"


def assert_healing(active_combat):
    return hp_change(active_combat, "Reef", 20, "HEALING") and hp_change(active_combat, "Calti", 15, "NOOP")


def melee_attack(active_combat):
    return hp_change(active_combat, "GFoY1", 53)


def monster_attack(active_combat):
    return all(
        [
            hp_change(active_combat, "Calti", 40, "DAMAGE"),
            hp_change(active_combat, "Noxxis Blazehammer", 55, "NOOP"),
            hp_change(active_combat, "KO2", 5, "NOOP"),
            hp_change(active_combat, "KO1", 2, "NOOP"),
            hp_change(active_combat, "TR1", 78, "NOOP"),
        ]
    )


def monster_firebreath(active_combat):
    return all(
        [
            hp_change(active_combat, "Calti", 45, "DAMAGE"),
            hp_change(active_combat, "Reef", 25, "DAMAGE"),
            hp_change(active_combat, "BU1", 86, "NOOP"),
            hp_change(active_combat, "YRD1", 178, "NOOP"),
        ]
    )


def monster_regen(active_combat):
    return all(
        [
            hp_change(active_combat, "TR1", 71, "HEALING"),
            hp_change(active_combat, "Ophizenya", 25, "NOOP"),
            hp_change(active_combat, "GV1", 22, "NOOP"),
            hp_change(active_combat, "Calti", 40, "NOOP"),
        ]
    )


def ranged_attack(active_combat):
    return hp_change(active_combat, "CE1", 32, "DAMAGE") and hp_change(active_combat, "Rahotur", 66, "NOOP")


def second_wind(active_combat):
    return all(
        [
            hp_change(active_combat, "Ophizenya", 18, "HEALING"),
            hp_change(active_combat, "Reef", 14, "NOOP"),
            hp_change(active_combat, "Calti", 41, "NOOP"),
        ]
    )


scenario_maps = {
    "fireball": assert_fireball,
    "bardic_inspiration": assert_bardic_inspiration,
    "bless": assert_bless,
    "fireball": assert_fireball,
    "firebolt": assert_firebolt,
    "healing": assert_healing,
    "melee_attack": melee_attack,
    "mon_dagger": monster_attack,
    "mon_fire_breath": monster_firebreath,
    "mon_troll": monster_regen,
    "ranged_attack": ranged_attack,
    "second_wind": second_wind,
}


def dump_players_to_mongo(casters: Iterable[dict]) -> None:
    # establish mongo connection
    collection = "characters"
    mongo_db[collection].drop()
    for caster in casters:
        if caster:
            primary_key = {field: caster[field] for field in ["owner", "upstream"]}
            mongo_db[collection].update_one(primary_key, {"$set": caster}, upsert=True)
    Character._cache.clear()


def dump_csu_to_mongo(state_updates: Iterable[dict]) -> None:
    collection = "combats"
    mongo_db[collection].drop()
    TEST_CHANNEL_ID = "314159265358979323"  # pi
    state_updates["channel"] = TEST_CHANNEL_ID
    mongo_db[collection].update_one({"channel": TEST_CHANNEL_ID}, {"$set": state_updates}, upsert=True)
    Combat._cache.clear()


def predict(prompt, gpt_kwargs):
    """Make call to gpt3"""
    if gpt_kwargs.get("model", None) is not None:
        gpt_kwargs["prompt"] = prompt
        response = openai.Completion.create(**gpt_kwargs)
        return response["choices"][0]["text"]


@requires_data()
async def test_all_assertions(avrae, dhttp):
    with open(dir_path / "unit_test_scenarios.jsonl") as f:
        scenarios = [json.loads(line) for line in f.readlines()]
    scorer = rouge_scorer.RougeScorer(['rouge1', 'rougeL'])
    gpt_kwargs = {"model": "davinci", "temperature": 0.7}
    results = []
    for scenario in scenarios:
        characters = scenario["characters"]
        scenario_name = scenario["scenario"]
        combat = scenario["combat"]
        ## dump characters and combats into db
        dump_players_to_mongo(characters)
        dump_csu_to_mongo(combat)
        prompt = scenario["prompt"]
        response = scenario["command"]
        # response = predict(prompt, gpt_kwargs)
        reference_command = scenario["command"]
        combat = await active_combat(avrae)
        # avrae.message(f"!spellbook", author_id=combat.current_combatant.controller_id)
        # else:
        avrae.message(f"{response} hit fail", author_id=combat.current_combatant.controller_id)
        await dhttp.drain()
        if scenario_maps[scenario_name](await active_combat(avrae)):
            pass_fail = "PASS"
        else:
            pass_fail = "FAIL"
        ghetto_logger(f"{scenario_name}: {pass_fail}")
        sglue = sentence_gleu([reference_command.split(' ')], response.split(' '))
        ghetto_logger(f"SENTENCE GLEU:{scenario_name}:{sglue}")
        rouge_scores = scorer.score(reference_command, response)
        results += [{
            "PASS_FAIL": pass_fail,
            "Scenario": scenario_name,
            "Sentence GLEU": sglue,
            "Reference": reference_command,
            "Generation": response,
            "RougeL P": rouge_scores["rougeL"].precision,
            "RougeL R": rouge_scores["rougeL"].recall,
            "RougeL F": rouge_scores["rougeL"].fmeasure,
            "Rouge1 P": rouge_scores["rouge1"].precision,
            "Rouge1 R": rouge_scores["rouge1"].recall,
            "Rouge1 F": rouge_scores["rouge1"].fmeasure
        }]
    
    df = pd.DataFrame(results)
    df.to_csv("/opt/results.csv")
    fraction_of_passes = sum([1/len(scenarios) for k in results if k["PASS_FAIL"]=="PASS"])
    average_sglue = df["Sentence GLEU"].mean()
    
    ghetto_logger("_______________________")
    ghetto_logger(f"Fraction of Passes : {fraction_of_passes}")
    ghetto_logger(f"Averge SGLUE : {average_sglue}")
    ghetto_logger(f"Average Rouge1 F {df['Rouge1 F'].mean()}")
    ghetto_logger(f"Average Rouge1 P {df['Rouge1 P'].mean()}")
    ghetto_logger(f"Average Rouge1 R {df['Rouge1 R'].mean()}")
    ghetto_logger(f"Average RougeL F {df['RougeL F'].mean()}")
    ghetto_logger(f"Average RougeL P {df['RougeL P'].mean()}")
    ghetto_logger(f"Average RougeL R {df['RougeL R'].mean()}")
