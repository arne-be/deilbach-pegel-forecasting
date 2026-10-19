# Website mockup

[mockup-kombi.html](mockup-kombi.html) is the agreed layout of the public forecast page, as one self-contained HTML file. Open it in a browser and switch states in the footer or by URL hash:

- `#normal`: the real prod forecast of 16.10.2026 (19 cm, rising to about 31 cm overnight)
- `#flood`: a made-up flood like the record of 19.11.2024: 128 cm now, 172 cm peak, 90 % range up to 197 cm
- `#stale`: the flood seen two hours later with no new data
- `#fallback`: the flood, but only the persistence model answered
- `#chaos`: the flood raised by 60 cm: 188 cm now, peak about 232 cm (category 5)

Debug hash for screenshots: `&hover=2026-11-19T22:22Z` sets the chart cursor.

Top to bottom:

1. **Title and verdict.** "Deilbach Pegel Vorhersage", then the expected category with its time and, when the 90 % range reaches a higher one, "Möglich: …". On the right the level now and the distance to 145 cm.
2. **Scene.** An isometric drawing of the site: the car park with its P sign (floods above 165 cm), the river, the wall with the gauge staff (water goes over it above 185 cm), the yard with the red mobile barriers (set up from category 3, above 165 cm, holding to 225 cm), sandbags (laid out above 165 cm) and the house (reached above 225 cm). The water flows at the current level. In category 5 it turns brown and a skip container drifts down the river. Hovering or dragging on the chart, or the arrow keys, moves the water to the level at that hour. Stale data turns it grey and still.
3. **Chart.** The last 24 h measured and the 24 h forecast over the five coloured category zones, with "Jetzt" at the newest reading; darker shading is the 80 % range, lighter the 90 % range. The y-axis always runs from 0 to 250 cm, so a level is seen against the categories; it grows only if a level goes higher.
4. **Stufen und Maßnahmen.** One card per category with its range, what happens and the actions, marked with the expected and earliest possible time from the forecast.
5. **So entsteht die Vorhersage.** Four steps: gauges, rain, model, ranges.

The earlier rounds are in this PR's history.

## Rules

- **Times** are hours, taken from the last forecast point before a line crosses a threshold, so they err early.
- **Stale or fallback means no forecast.** No verdict, no forecast in the chart or the scene, a badge with the time of the newest reading and a link to the Hochwasserportal NRW. Freshness is rechecked every minute.
- **Categories** start strictly above their threshold (145,0 cm is still Kat. 1), as in `core/categories.py`.
- **Styling** follows energiekonzepte-ruhr.de; the mockup hotlinks the client's logo, the real page will copy it.
- **The scene** is plain SVG and JavaScript, no 3D library. Water levels are to scale; cars and the house are drawn to look natural.

## Open before building

- **Actions in config.** The category texts and actions should move into `config/pegel.json`, next to the categories, so the page and the docs read the same source. The mockup follows the owner's text, where each text says what happens at the start of its category: the car park floods and barriers and sandbags go out above 165 cm (category 3), the water goes over the wall above 185 cm, and over the barriers to the house above 225 cm.
- **False alarms.** Before "Möglich: …" ships, count how often the 90 % top would have warned for nothing on the evaluation data (`false_alarms.csv`); switch to the 80 % range if it warns too often.
- **12 h** isn't needed any more; the page uses the whole 24 h forecast.
- **Touch on real phones** is untested; the drag only starts on a sideways move, so vertical scrolling keeps working.
