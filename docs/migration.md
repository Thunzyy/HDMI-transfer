# Migration

## Regle simple

Quand vous touchez du code, utilisez les modules canoniques. Les anciens imports restent supportes pour ne pas casser les scripts existants, mais ils ne sont plus la cible de developpement.

## Mappage des modules

| Legacy | Canonique |
|--------|-----------|
| `hdmi_exfil.config` | `hdmi_exfil.core.config` |
| `hdmi_exfil.prng` | `hdmi_exfil.core.prng` |
| `hdmi_exfil.protocols.*` | `hdmi_exfil.core.protocols.*` |
| `hdmi_exfil.capture.*` | `hdmi_exfil.core.capture.*` |
| `hdmi_exfil.file_handling.*` | `hdmi_exfil.core.file_handling.*` |
| `hdmi_exfil.display.*` | `hdmi_exfil.sender.display.*` |
| `hdmi_exfil.sender.cli.*` | `hdmi_exfil.interfaces.cli.*` |
| `hdmi_exfil.receiver.cli.*` | `hdmi_exfil.interfaces.cli.*` |
| `hdmi_exfil.web.server` | `hdmi_exfil.interfaces.web.app_factory` |

## Nouveaux points d'entree

| Usage | Point d'entree |
|------|----------------|
| Sender CLI | `hdmi_exfil.interfaces.cli.send` |
| Receiver CLI | `hdmi_exfil.interfaces.cli.receive` |
| Calibration CLI | `hdmi_exfil.interfaces.cli.calibrate` |
| Sender console | `hdmi_exfil.interfaces.cli.sender_console` |
| Receiver console | `hdmi_exfil.interfaces.cli.receiver_console` |
| Web app | `hdmi_exfil.interfaces.web.create_app` |

## Sender navigateur

- Le protocole JS n'est plus edite a la main dans `sender.html`.
- Modifier les sources dans `src/hdmi_exfil/interfaces/browser_sender/`.
- Regenerer ensuite:

```bash
python tools/build_sender_html.py
python tools/build_sender_html.py --check
```

## Comment migrer une zone legacy

1. Trouver le chemin canonique cible.
2. Deplacer la logique reelle dans `domain`, `application`, `adapters` ou `interfaces`.
3. Laisser le module legacy comme wrapper explicite via `hdmi_exfil.compat.imports.reexport`.
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
