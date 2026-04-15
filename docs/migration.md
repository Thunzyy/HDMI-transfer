# Migration

## Regle simple

Quand vous touchez du code, utilisez les modules canoniques. Les anciens imports restent supportes pour ne pas casser les scripts existants, mais ils ne sont plus la cible de developpement.

## Mappage des modules

| Legacy | Canonique |
|--------|-----------|
| `hdmi_transfer.config` | `hdmi_transfer.core.config` |
| `hdmi_transfer.prng` | `hdmi_transfer.core.prng` |
| `hdmi_transfer.protocols.*` | `hdmi_transfer.core.protocols.*` |
| `hdmi_transfer.capture.*` | `hdmi_transfer.core.capture.*` |
| `hdmi_transfer.file_handling.*` | `hdmi_transfer.core.file_handling.*` |
| `hdmi_transfer.display.*` | `hdmi_transfer.sender.display.*` |
| `hdmi_transfer.sender.cli.*` | `hdmi_transfer.interfaces.cli.*` |
| `hdmi_transfer.receiver.cli.*` | `hdmi_transfer.interfaces.cli.*` |
| `hdmi_transfer.web.server` | `hdmi_transfer.interfaces.web.app_factory` |

## Nouveaux points d'entree

| Usage | Point d'entree |
|------|----------------|
| Sender CLI | `hdmi_transfer.interfaces.cli.send` |
| Receiver CLI | `hdmi_transfer.interfaces.cli.receive` |
| Calibration CLI | `hdmi_transfer.interfaces.cli.calibrate` |
| Sender console | `hdmi_transfer.interfaces.cli.sender_console` |
| Receiver console | `hdmi_transfer.interfaces.cli.receiver_console` |
| Web app | `hdmi_transfer.interfaces.web.create_app` |

## Sender navigateur

- Le protocole JS n'est plus edite a la main dans `sender.html`.
- Modifier les sources dans `src/interfaces/browser_sender/`.
- Regenerer ensuite:

```bash
uv run python tools/build_sender_html.py
uv run python tools/build_sender_html.py --check
```

## Comment migrer une zone legacy

1. Trouver le chemin canonique cible.
2. Deplacer la logique reelle dans `domain`, `application`, `adapters` ou `interfaces`.
3. Laisser le module legacy comme wrapper explicite via `hdmi_transfer.compat.imports.reexport`.
4. Ajouter ou mettre a jour les tests de compatibilite.

## Politique de compatibilite

- Les shims legacy restent acceptes tant que les scripts publics et les imports historiques doivent continuer a fonctionner.
- Les nouveaux tests doivent viser les modules canoniques.
- Si vous voulez visualiser les imports a migrer, definir `HDMI_EXFIL_WARN_LEGACY_IMPORTS=1`.

## Ce qui ne doit plus arriver

- Une seconde implementation du protocole dans le sender navigateur.
- Une logique de decodage dans `receiver_worker.py` ou dans une route Flask.
- Une logique de session dans `sender/cli/send.py` ou `receiver/cli/receive.py`.
- Une gestion ad hoc du cycle de vie de capture dans le code web.
