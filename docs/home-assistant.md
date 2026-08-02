# Home Assistant bridge

Food Assistant 0.23 provides an authenticated aggregate API and native Home
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
recipe, links, and generation time.

## Add the kitchen view

Use `integrations/home-assistant/lovelace-kitchen.yaml.example` as a YAML-mode
dashboard view, or reproduce its native Markdown, Grid, Button, Glance, and
Conditional cards in the visual editor. It works on a Surface in landscape and
on a phone in portrait. No frontend card receives the API credential.

The view can choose another recipe, mark it cooked with confirmation, refresh,
open Mealie, manage pantry inventory, and show all recommendations. It has
friendly empty and unavailable states.

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
