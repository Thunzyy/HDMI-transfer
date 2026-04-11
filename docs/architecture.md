# Architecture

## Objectif

Le projet est maintenant structure autour d'un moteur de transfert unique, d'un manifest protocolaire unique, et d'interfaces minces. Le code UI, CLI et web n'embarque plus sa propre logique protocolaire.

## Couches

```text
src/hdmi_exfil/
  domain/          Donnees canoniques du protocole
  application/     Sessions send/receive et evenements
  adapters/        Capture, stockage et integrations techniques
  interfaces/      CLI, web Flask et sender navigateur
  compat/          Shims d'import legacy, explicites et testes
```

## Responsabilites

| Couche | Role | Ce qui n'a pas le droit d'y vivre |
|--------|------|------------------------------------|
| `domain` | Manifest protocolaire, modeles immuables, constantes partagees | IO, capture, Flask, pygame, OpenCV |
| `application` | Orchestration de session, evenements, progression, cutover send/receive | Acces materiel direct, rendu UI |
| `adapters` | Capture persistante, registry devices, stockage et bridges techniques | Regles metier du protocole |
| `interfaces` | Commandes CLI, routes web, preview, generation sender HTML | Etats de protocole, heuristiques de decodage |
| `compat` | Reexports legacy uniformes et strategie d'avertissement | Nouvelle logique produit |

## Source de verite

- `hdmi_exfil.domain.protocol_manifest` est la source de verite pour les profils, magics, tailles de header et parametres exposes au sender navigateur.
- `tools/build_sender_html.py` genere `sender.html` et `protocol.generated.js` a partir du manifest. Le HTML standalone n'est plus une implementation manuelle du protocole.
- `hdmi_exfil.application.send_session.SendSession` et `hdmi_exfil.application.receive_session.ReceiveSession` portent les machines d'etat communes. CLI et web appellent ces services au lieu de dupliquer la logique.

## Flux d'envoi

1. L'interface CLI ou web collecte les options utilisateur.
2. `SendSession` lit le payload, construit les metadonnees et produit les packets/frame events.
3. Le renderer choisi affiche les frames.
4. Le sender navigateur suit le meme contrat protocolaire via les assets generes.

## Flux de reception

1. `CaptureManager` ouvre ou reutilise une capture persistante.
2. La couche interface lit les frames et les transforme en grilles echantillonnees.
3. `ReceiveSession` detecte le protocole, gere la progression et reconstruit le fichier.
4. Les routes web ou le CLI ne font qu'exposer les evenements et les fichiers produits.

## Web app

- `hdmi_exfil.interfaces.web.app_factory.create_app` cree l'application Flask.
- `routes_devices.py`, `routes_receive.py` et `routes_files.py` portent le routage HTTP.
- `preview_stream.py` reste dans la couche interface car il expose un flux HTTP, mais il depend du `CaptureManager` pour la capture.
- `hdmi_exfil.web.server` est desormais un shim de compatibilite.

## Compatibilite

- Les anciens imports (`hdmi_exfil.protocols`, `hdmi_exfil.config`, `hdmi_exfil.cli.*`, etc.) restent disponibles via `hdmi_exfil.compat.imports.reexport`.
- Les wrappers legacy peuvent emettre un avertissement si `HDMI_EXFIL_WARN_LEGACY_IMPORTS=1`.
- Toute nouvelle contribution doit viser les chemins canoniques, pas les shims.

## Regles de qualite

- Les performances fountain sont bloquees par `tests/test_fountain_overhead.py` et `tests/perf/test_fountain_budget.py`.
- La generation du sender navigateur est verifiee par `python tools/build_sender_html.py --check`.
- Le gate local et CI passe par `tools/run_quality_gate.ps1`.

## Decision importante

Le projet reste en strangler refactor: les shims legacy existent encore, mais l'architecture cible est deja en place. Le prochain travail doit retirer les points morts, pas reintroduire de logique protocolaire dans les interfaces.
