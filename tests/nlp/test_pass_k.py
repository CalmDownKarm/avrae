import os
import json
import openai
import asyncio
import datetime
import pandas as pd
from pathlib import Path
from typing import Iterable
from pymongo import MongoClient
from collections import defaultdict
from rouge_score import rouge_scorer
from cogs5e.initiative.combat import Combat
from cogs5e.models.character import Character
from nltk.translate.gleu_score import sentence_gleu

dir_path = Path(__file__).parent

mongodb_url = os.getenv("MONGO_URL")
mongo_client = MongoClient(mongodb_url)
mongo_db = mongo_client.avrae

with open("/opt/logfile", "w") as f:
    f.write(f"{datetime.datetime.now()}")


def ghetto_logger(string_to_log):
    with open("/opt/logfile", "a") as f:
        f.write(f"\n{string_to_log}")

from tests.utils import active_combat, requires_data

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


@requires_data()
async def test_pass_k(avrae, dhttp, record_command_errors):
    with open(dir_path / "utt-cmd-test-results-ready-for-eval.jsonl") as f:
        utterances = [json.loads(line) for line in f.readlines()]
    scorer = rouge_scorer.RougeScorer(["rouge1", "rougeL"])
    results = []

    for utterance in utterances:
        combat_state = utterance["combat_state"]
        characters = utterance["characters"]
        model_results = defaultdict(list)
        reference = utterance["gold"]
        speaker_id = utterance["speaker_id"]
        models = ("gold", "prediction_full", "prediction_nostate", "precition_fewshot_full", "prediction_fewshot_nostate")
        for model in models:
            dump_players_to_mongo(characters)
            dump_csu_to_mongo(combat_state)
            combat = await active_combat(avrae)
            avrae.message(f"{utterance[model]} hit fail", author_id=speaker_id)
            pass_fail = "FAIL"
            try:
                await dhttp.drain()
                pass_fail = "PASS"
            except asyncio.TimeoutError:
                pass_fail = "FAIL"
            else:
                if record_command_errors:
                    pass_fail = "FAIL"
            model_results["pass_fail"].append(pass_fail)
            sglue = sentence_gleu([reference.split(" ")], utterance[model].split(" "))
            rouge_scores = scorer.score(reference, utterance[model])
            model_results["gleu"].append(sglue)
            model_results["rouge1"].append(rouge_scores["rouge1"].fmeasure)
            model_results["rougeL"].append(rouge_scores["rougeL"].fmeasure)
            record_command_errors.clear()
        results.append(model_results)
        ghetto_logger(f"model_results {model_results}")
    pass_fail = pd.DataFrame([res["pass_fail"] for res in results])
    pass_fail.columns = [f"pf_{m}" for m in models]
    sglue = pd.DataFrame([res["gleu"] for res in results])
    sglue.columns = [f"gleu_{m}" for m in models]
    rouge1 = pd.DataFrame([res["rouge1"] for res in results])
    rouge1.columns = [f"r1_{m}" for m in models]
    rougeL = pd.DataFrame([res["rougeL"] for res in results])
    rougeL.columns = [f"rL_{m}" for m in models]
    total = pd.concat([pass_fail, sglue, rouge1, rougeL], axis=1).to_csv("/opt/results.csv")
