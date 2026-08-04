# Home Assistant bridge

Food Assistant 0.25.1 provides authenticated aggregate and active-cooking APIs and native Home
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

Unknown or unavailable selector states safely fall back to `ready_now`; the
package never sends arbitrary selector text. To refresh both REST sensors from
Developer Tools, use the service data form expected by Home Assistant:

```yaml
action: homeassistant.update_entity
data:
  entity_id:
    - sensor.food_assistant
    - sensor.food_assistant_cooking
```
