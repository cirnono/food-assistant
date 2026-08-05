from __future__ import annotations

import re
import yaml

from app.schemas import ShoppingListCreate

SENTENCE_PATH = "integrations/home-assistant/custom_sentences/zh-CN/food_assistant.yaml.example"
PACKAGE_PATH = "integrations/home-assistant/food_assistant_package.yaml.example"

class SecretLoader(yaml.SafeLoader):
    pass

SecretLoader.add_constructor("!secret", lambda loader, node: loader.construct_scalar(node))

def _load():
    with open(SENTENCE_PATH, encoding="utf-8") as file:
        sentences = yaml.safe_load(file)
    with open(PACKAGE_PATH, encoding="utf-8") as file:
        package = yaml.load(file, Loader=SecretLoader)
    return sentences, package

def _sentences(intent):
    return [sentence for row in intent["data"] for sentence in row["sentences"]]

def test_zh_cn_intents_are_unique_and_map_one_to_one():
    sentences, package = _load()
    assert sentences["language"] == "zh-CN"
    sentence_intents = set(sentences["intents"])
    assert len(sentence_intents) == 10
    assert sentence_intents == set(package["intent_script"])
    assert all(name.startswith("FoodAssistant") for name in sentence_intents)

def test_finish_requires_explicit_confirmation_and_no_punctuation():
    sentences, _ = _load()
    finish = _sentences(sentences["intents"]["FoodAssistantConfirmFinishCooking"])
    assert "确认完成烹饪" in finish
    assert not {"做完了", "好了", "结束", "完成"} & set(finish)
    all_rows = [s for intent in sentences["intents"].values() for s in _sentences(intent)]
    assert all(not re.search(r"[，。！？,.!?]", sentence) for sentence in all_rows)
    assert len(all_rows) == len(set(all_rows))

def test_only_shopping_item_uses_a_local_wildcard():
    sentences, _ = _load()
    wildcard_rows = []
    for intent_name, intent in sentences["intents"].items():
        for row in intent["data"]:
            for list_name, definition in row.get("lists", {}).items():
                if definition.get("wildcard") is True:
                    wildcard_rows.append((intent_name, list_name))
    assert wildcard_rows == [("FoodAssistantAddShoppingItem", "item")]
    shopping = _sentences(sentences["intents"]["FoodAssistantAddShoppingItem"])
    assert "把{item}加入购物清单" in shopping
    assert not {"买{item}", "要{item}", "加{item}"} & set(shopping)

def test_references_exist_and_voice_wrappers_are_single():
    _, package = _load()
    scripts, commands = package["script"], package["rest_command"]
    required = {"food_assistant_next_recipe", "food_assistant_start_cooking", "food_assistant_next_step", "food_assistant_previous_step", "food_assistant_finish_cooking"}
    assert required <= scripts.keys()
    assert required <= commands.keys()
    wrappers = {name: value for name, value in scripts.items() if "_voice_" in name}
    assert len(wrappers) == 6
    assert all(value["mode"] == "single" for value in wrappers.values())

def test_shopping_payload_is_trimmed_safe_and_does_not_guess_quantity():
    _, package = _load()
    command = package["rest_command"]["food_assistant_add_shopping_item"]
    assert "item_name | trim | tojson" in command["payload"]
    assert '"quantity":null' in command["payload"]
    assert '"unit":null' in command["payload"]
    assert "item_name" not in command["url"]
    wrapper = yaml.safe_dump(package["script"]["food_assistant_voice_add_shopping_item"], allow_unicode=True)
    assert "clean_item | length > 0" in wrapper
    speech = package["intent_script"]["FoodAssistantAddShoppingItem"]["speech"]["text"]
    assert "已提交" in speech and "已新增" not in speech

    backend_payload = ShoppingListCreate(name="  鸡蛋两盒  ")
    assert backend_payload.name == "鸡蛋两盒"
    assert backend_payload.quantity is None
    assert backend_payload.unit is None

def test_voice_safety_boundaries_and_safe_templates():
    _, package = _load()
    serialized = yaml.safe_dump(package, allow_unicode=True)
    finish = yaml.safe_dump(package["script"]["food_assistant_voice_finish_cooking"], allow_unicode=True)
    assert "sensor.food_assistant_cooking" in finish and "state: active" in finish
    assert "confirm_consumption" not in serialized
    assert "/0/next-step" not in serialized
    speech = yaml.safe_dump(package["intent_script"], allow_unicode=True)
    for value in ("unknown", "unavailable", "none", "step_count", "前几项暂时无法读取", "total_time_minutes"):
        assert value in speech
