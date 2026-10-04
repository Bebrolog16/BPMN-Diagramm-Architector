# BPMN Architect colorbook

The UI uses a semantic green palette defined in `web/static/colorbook.css`.
Add or adjust colors there instead of scattering new hex values through the UI.

| Token | Light value | Use |
| --- | --- | --- |
| `--brand-50`–`--brand-900` | Green scale from `#effaf3` to `#10442f` | Brand shades and emphasis |
| `--accent-color` | `#19814f` | Primary actions, focus and links |
| `--accent-color-strong` | `#146641` | Hover state for primary actions |
| `--accent-soft` | Green at 10% opacity | Selected controls and subtle fills |
| `--success-color` | `#19814f` | Positive state |
| `--danger-color` | `#b84f5e` | Destructive actions and errors |
| `--text-main` / `--text-secondary` | `#202a25` / `#65736b` | Main and supporting text |
| `--glass-fill` / `--glass-border` | Translucent white | Panels and glass surfaces |
| `--canvas-dot` | Muted green-gray | BPMN canvas dot map |

Dark mode overrides the same semantic tokens on `body[data-theme="dark"]`; component styles should consume the tokens rather than define separate theme colors.
