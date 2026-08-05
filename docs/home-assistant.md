# Home Assistant bridge

Food Assistant 0.26.0 provides authenticated aggregate and active-cooking APIs and native Home
Assistant examples. It requires neither HACS nor MQTT Discovery. Food Assistant
and Home Assistant must be able to reach one another over the network.

## Configure secrets

Add these entries to HA's `secrets.yaml`, replacing the documentation hostname
with an address reachable from Home Assistant:

```yaml
food_assistant_state_url: http://food-assistant.example:8787/api/v1/home-assistant/state
food_assistant_next_url: http://food-assistant.example:8787/api/v1/home-assistant/selection/next
food_assistant_mark_cooked_url: http://food-assistant.example:8787/api/v1/home-assistant/selection/mark-cooked
food_assistant_refresh_url: http://food-assistant.example:8787/api/v1/home-assistant/refresh
food_assistant_cooking_state_url: http://food-assistant.example:8787/api/v1/cooking-sessions/active-state?owner=household
food_assistant_authorization: Bearer <FOOD_ASSISTANT_API_TOKEN>
```

Keep authorization only in `secrets.yaml`; never put it in Lovelace, entity
attributes, screenshots, logs, or source control. Rotate it by updating the
Food Assistant credential and HA secret together, then restart both services.

## Enable the package

Enable packages in `configuration.yaml` if necessary:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Copy `integrations/home-assistant/food_assistant_package.yaml.example` to HA as
`packages/food_assistant.yaml`. Run **Developer Tools → YAML → Check
configuration**, restart HA, and confirm `sensor.food_assistant` becomes `ok`.
Its attributes contain inventory, recommendation counts, the stable selected
recipe, active-cooking summary, links, and generation time. The additional
`sensor.food_assistant_cooking` polls only local SQLite state every ten seconds;
it does not contact Mealie or run the recommendation engine.

## Add the kitchen view

Use `integrations/home-assistant/lovelace-kitchen.yaml.example` as a YAML-mode
dashboard view, or reproduce its native Markdown, Grid, Button, Glance, and
Conditional/Entities cards in the visual editor. It works on a Surface in landscape and
on a phone in portrait. No frontend card receives the API credential.

The view can choose another recipe, start or continue a cooking session, move
between steps, finish or cancel with confirmation, refresh, open Mealie, manage
pantry inventory, and show all recommendations. Idle and active layouts switch
automatically and have friendly empty and unavailable states. `/cook` is the
full touch-first Surface/mobile interface for ingredient check-off and timers.

Set `HOME_ASSISTANT_KITCHEN_URL` only on the Food Assistant host when `/cook`
should show a return link to a kitchen dashboard. Keep the public example empty;
the URL is optional and contains no credential.

## Troubleshooting

- **401**: verify the `Bearer ` prefix and rotate both configured values.
- **Connection failure**: check DNS, routing, ports, and firewall rules.
- **`selected_recipe=null`**: add available inventory or relax the mode/filter.
- **Cold cache is slow**: first load or explicit cache refresh reads Mealie;
  later five-minute polls reuse the six-hour cache.
- **Mealie unavailable**: check Mealie health and Food Assistant logs. One bad
  recipe is ignored, but a complete list failure prevents state refresh.

Polling never changes a valid selection. Only explicit next/cooked actions, a
missing recipe, or a newly violated hard filter changes it.

Choose the recommendation mode from the dashboard's native selector:

- `ready_now`: only recipes possible with current inventory.
- `missing_one_or_two`: recipes missing one or two ingredients.
- `use_soon`: prioritize ingredients approaching expiry.

On first installation, when Home Assistant has no state to restore, the selector
starts with the first option, `missing_one_or_two`. After the user chooses a
mode, Home Assistant restores that last state across restarts. For everyday
household use, `missing_one_or_two` is the default.

Unknown or unavailable selector states safely fall back to `missing_one_or_two`; the
package never sends arbitrary selector text. To refresh both REST sensors from
Developer Tools, use the service data form expected by Home Assistant:

```yaml
action: homeassistant.update_entity
data:
  entity_id:
    - sensor.food_assistant
    - sensor.food_assistant_cooking
```

## Simplified Chinese Assist

The 0.26.0 examples add deterministic `zh-CN` custom sentences and native
`intent_script` handlers. They do not use an LLM, a custom integration, or
HACS. Set the Assist pipeline language to **zh-CN**; another pipeline language
will not load these sentences.

Supported intents are:

- recommendation query and next recommendation;
- start cooking, current/next/previous step, and explicitly confirmed finish;
- shopping summary and adding one literal shopping-item name;
- pending inventory-consumption review count.

Voice deliberately cannot confirm a consumption review, deduct pantry stock,
complete/delete a shopping item, delete cooking history, cancel cooking, or
overwrite historical data. Only “确认完成烹饪”, “确认这道菜做完了”, and
“确认结束本次烹饪” can invoke cooking completion. Short phrases such as “做完了”,
“好了”, “结束”, and “完成” do not match that intent. Finishing creates a pending
consumption review; it does not confirm the review or change inventory.

### Interface and execution audit

The package reuses the existing `food_assistant_next_recipe`,
`food_assistant_start_cooking`, `food_assistant_next_step`,
`food_assistant_previous_step`, and `food_assistant_finish_cooking` scripts and
their REST commands. Dashboard scripts remain unchanged. Voice-only wrappers
use `mode: single` and check state before calling them.

- Starting requires cooking state `idle`, a selected recipe, and a non-empty
  selected slug. The backend also serializes each owner, rejects an existing
  active session, confirms the slug, and requires valid recipe steps.
- Step changes require an active session, a positive session ID, a matching
  owner/confirmation ID, and an in-range target step. Voice wrappers never
  construct a `/0/next-step` or `/0/previous-step` request.
- Finishing requires an active confirmed session. It atomically records cooking
  history, queues a consumption review, completes timers, and selects another
  recommendation. It does not decrement pantry quantities.
- Shopping creation uses `ShoppingListCreate`: `owner`, trimmed `name`, null
  `quantity`/`unit`, normal priority, manual source, and a fixed Assist note.
  The backend enforces the schema and name length, canonicalizes the name, and
  may merge it with an active compatible item. A phrase such as “鸡蛋两盒” is
  passed as the literal name; voice does not infer quantity or unit.
- Recommendation sensors expose the selected name, time, missing ingredients,
  and counts. Cooking sensors expose active state, recipe, current step/count,
  progress, and timers. Shopping sensors expose total count and only a five-item
  preview. Consumption exposes only the pending-review count.
- Existing dashboard scripts run sequentially and refresh sensors after REST
  calls. Backend owner locks and confirmation fields reject stale or concurrent
  state changes. Voice wrappers add single-run protection and preconditions;
  failed actions do not claim that an item was newly created.

Every voice operation that changes data is bounded: next recommendation changes
only the stable selection; starting/step navigation/finishing changes only the
cooking session and the documented finish side effects; shopping add submits
one manual item for backend merge. No destructive or inventory-confirming voice
intent exists.

### Install the sentence file

The custom-sentence example cannot remain only in the Food Assistant checkout.
It must be copied into Home Assistant's
`/config/custom_sentences/zh-CN/food_assistant.yaml`. For the documented host
layout:

```bash
mkdir -p /srv/appdata/homeassistant/custom_sentences/zh-CN

sudo install \
  -m 0644 \
  integrations/home-assistant/custom_sentences/zh-CN/food_assistant.yaml.example \
  /srv/appdata/homeassistant/custom_sentences/zh-CN/food_assistant.yaml
```

Install the updated package example as `packages/food_assistant.yaml`, run Home
Assistant `check_config`, restart Home Assistant, and verify that the Assist
pipeline language is `zh-CN`. Test in the Assist text box first, then test a
voice device. From the Food Assistant checkout, the read-only validation is:

```bash
bash scripts/check-home-assistant-assist.sh
```

The checker parses examples and compares sentence/handler names. It does not
read `secrets.yaml`, credentials, or production configuration and makes no
changes.

### Responses and failures

Templates handle unknown/unavailable sensors, absent recipes or sessions, zero
steps, missing time, and an empty shopping preview. Speech never includes a URL,
entity ID, internal/session ID, Mealie slug, credential, raw HTTP response, or
traceback. Operational failures should be interpreted as:

- 401: “Food Assistant 认证失败，请检查 Home Assistant 配置。”
- 409: “当前状态不允许执行这个操作。”
- 422: “语音参数无效，请换一种说法。”
- 502/503: “菜谱服务暂时不可用，请稍后再试。”
- other: “操作没有完成，请检查 Food Assistant 状态。”

Home Assistant stops a failed REST action and records the diagnostic in its own
log; the example does not catch failures and then announce success. The
Authorization value remains only in the existing HA secret and is never sent in
a URL, sentence, or speech response.

### Text testing

Prefer **Home Assistant UI → Assist** and enter a sentence such as “今天吃什么”.
Optionally, an administrator can call the Conversation API without printing or
documenting a long-lived access token:

```http
POST /api/conversation/process
Content-Type: application/json

{
  "text": "今天吃什么",
  "language": "zh-CN"
}
```

The API returns a conversation response. Never paste a real token into source
control, screenshots, shell history, or documentation.
