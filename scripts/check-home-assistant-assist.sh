#!/usr/bin/env bash
set -euo pipefail

package="integrations/home-assistant/food_assistant_package.yaml.example"
sentences="integrations/home-assistant/custom_sentences/zh-CN/food_assistant.yaml.example"
[[ -f "$package" ]] || { echo "missing package example" >&2; exit 1; }
[[ -f "$sentences" ]] || { echo "missing zh-CN sentence example" >&2; exit 1; }

python3 - "$package" "$sentences" <<'PY'
import re
import sys
from pathlib import Path
import yaml

class SecretLoader(yaml.SafeLoader):
    pass

SecretLoader.add_constructor("!secret", lambda loader, node: loader.construct_scalar(node))
package_path, sentence_path = map(Path, sys.argv[1:])
package_text = package_path.read_text(encoding="utf-8")
sentence_text = sentence_path.read_text(encoding="utf-8")
package = yaml.load(package_text, Loader=SecretLoader)
sentences = yaml.safe_load(sentence_text)
sentence_intents = set(sentences.get("intents", {}))
script_intents = set(package.get("intent_script", {}))
if sentences.get("language") != "zh-CN":
    raise SystemExit("sentence language must be zh-CN")
if sentence_intents != script_intents:
    raise SystemExit(f"intent mismatch: sentences={sorted(sentence_intents)}, scripts={sorted(script_intents)}")
if any(not name.startswith("FoodAssistant") for name in sentence_intents):
    raise SystemExit("all custom intents must use the FoodAssistant prefix")
dangerous = ("confirm consumption", "deduct inventory", "delete shopping item", "delete history", "确认消耗", "扣减库存", "删除购物", "删除历史")
found = [term for term in dangerous if term in sentence_text.lower()]
if found:
    raise SystemExit(f"dangerous voice intent found: {found}")
if re.search(r"Authorization\s*:", sentence_text, re.IGNORECASE):
    raise SystemExit("sentence file must not contain authorization configuration")

serialized_intents = yaml.safe_dump(package["intent_script"], allow_unicode=True)
script_refs = set(re.findall(r"script\.([a-z0-9_]+)", serialized_intents))
rest_refs = set(re.findall(r"rest_command\.([a-z0-9_]+)", serialized_intents))
missing_scripts = script_refs - set(package.get("script", {}))
missing_rest = rest_refs - set(package.get("rest_command", {}))
if missing_scripts or missing_rest:
    raise SystemExit(
        f"missing references: scripts={sorted(missing_scripts)}, rest={sorted(missing_rest)}"
    )
required_entities = {
    "sensor.food_assistant",
    "sensor.food_assistant_cooking",
    "sensor.food_assistant_recipe",
    "sensor.food_assistant_recipe_missing",
    "sensor.food_assistant_shopping_count",
    "sensor.food_assistant_shopping_preview",
    "sensor.food_assistant_pending_consumption",
}
for entity_id in required_entities:
    unique_id = entity_id.removeprefix("sensor.")
    if entity_id not in package_text and f"unique_id: {unique_id}" not in package_text:
        raise SystemExit(f"missing required entity reference: {entity_id}")
print(f"Home Assistant Assist examples OK: {len(sentence_intents)} intents")
PY
