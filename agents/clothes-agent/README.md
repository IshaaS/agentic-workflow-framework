# agentctl-clothes-agent

Agent `clothes_adviser`, capability `clothes.advise`: `weather`, `activity` →
`clothing_requirements`.

Inputs:
- `weather`: the weather agent's output.
- `activity`: one of `outdoor_walk`, `theatre`, `casual`, `office`. Aliases:
  `walk` and `walking` mean `outdoor_walk`; `work` and `office_meeting` mean
  `office`.
- `style` (optional): `casual` (default), `business_casual` or `formal`.

Activity and style ignore case, and runs of spaces, hyphens and underscores
count as one underscore, so `Office Meeting` and `business casual` are
accepted. Any other value is rejected with the list of supported values. The
manifest advertises the canonical activities plus the aliases, so request mode
(`--request`) accepts them too.

Output: four categories, each a list of clothing types, best fit first. An
empty `outerwear` list means no jacket is needed.

```python
{"clothing_requirements": {"top": ["t_shirt", "polo"], "bottom": ["pants", "jeans"],
                           "outerwear": ["rain_jacket", "light_jacket"],
                           "footwear": ["walking_shoes", "sneakers"]}}
```

The rules are deterministic Python; no external services are used. The full
rules, thresholds and order of precedence are in the docstring of
`agentctl_agents/clothes/agent.py`. In summary:
- Temperature: cold is below 10°C, mild is 10–20°C, warm is above 20°C.
- Wet: the condition is rainy or stormy, or the chance of rain is at least 50%.
- Windy: wind speed is at least 30 km/h.
- Dress level: theatre and office are at least smart (business casual);
  `business_casual` or `formal` style makes other activities smart, and
  `formal` style at the theatre or office makes them formal.
- Office: assumes a commute, so rain calls for a rain jacket; prefers a dress
  shirt or polo, pants and dress shoes.

Clothing types:

| Category | Types |
|---|---|
| top | `t_shirt`, `polo`, `long_sleeve_shirt`, `sweater`, `dress_shirt` |
| bottom | `shorts`, `jeans`, `pants`, `dress_pants` |
| outerwear | `light_jacket`, `rain_jacket`, `winter_coat`, `blazer` |
| footwear | `sneakers`, `walking_shoes`, `boots`, `dress_shoes` |

These must match the `clothing_type` values in the shelf agent's database.
The tests check that the two stay aligned.
