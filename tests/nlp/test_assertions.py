import os
import json
import openai

with open("./openai_key.txt") as f:
    openai.api_key = f.read()
os.environ["OPENAI_API_KEY"] = openai.api_key
from avrae.tests.utils import active_combat


def assert_fireball(active_combat):
    ...


async def assert_bardic_inspiration(active_combat):
    effects = (await active_combat).get_combatant("Noxxis Blazehammer").get_effects()
    assert len(effects) == 1
    assert effects[0].name == "Feeling Inspired"


scenarios = {"fireball": assert_fireball, "bardic_inspiration": assert_bardic_inspiration}


def predict(prompt, gpt_kwargs):
    """Make call to gpt3"""
    if gpt_kwargs.get("model", None) is not None:
        gpt_kwargs["prompt"] = prompt
        response = openai.Completion.create(**gpt_kwargs)
        return response["choices"][0]["text"]


async def test_all_assertions(avrae, dhttp):
    with open("./unit_test_scenarios.jsonl") as f:
        scenarios = [json.loads(line) for line in f.readlines()]
    gpt_kwargs = {"model": "davinci", "temperature": 0.7}
    for scenario in scenarios:
        characters = scenario["characters"]
        scenario_name = scenario["scenario"]
        combat = scenario["combat"]
        ## dump characters and combats into db
        prompt = scenario["prompt"]
        response = predict(prompt, gpt_kwargs)
        combat = await active_combat(avrae)
        avrae.message(response, author_id=combat.current_combatant.controller_id)
        await dhttp.drain()
        scenarios[scenario_name](await active_combat(avrae))
