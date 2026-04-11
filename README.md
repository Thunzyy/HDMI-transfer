# HDMI Exfil

Transfert de fichiers par signal video HDMI. Le sender encode un payload dans des frames affichees sur un ecran, le receiver lit ce signal via une carte de capture et reconstruit le fichier sans canal reseau.

Deux chemins d'envoi restent supportes :
- `hdmi-send` pour le sender Python
- `sender.html` pour le sender navigateur genere depuis la meme source protocolaire

## Architecture

Le projet est maintenant organise autour d'une architecture cible explicite :

```text
src/hdmi_exfil/
  domain/          Manifest protocolaire canonique
  application/     Sessions shared send/receive
  adapters/        Capture manager, registry devices, bridges techniques
  interfaces/      CLI, web Flask et sender navigateur
  compat/          Shims legacy testes et uniformes
```

Points importants :
- `hdmi_exfil.domain.protocol_manifest` est la source de verite des profils, headers et constantes partagees.
- `SendSession` et `ReceiveSession` portent les machines d'etat communes.
- `sender.html` est un artefact genere par `python tools/build_sender_html.py`, pas une implementation maintenue a la main.
- Les anciens imports restent disponibles, mais tout nouveau code doit viser les modules canoniques.

Documentation associee :
- [Architecture](docs/architecture.md)
- [Migration](docs/migration.md)
- [Testing](docs/testing.md)
- [Setup materiel](docs/hardware-setup.md)

## Installation

Python 3.11+ requis.

```bash
git clone git@github.com:Thunzyy/HDMI_exfil.git
cd HDMI_exfil
```

Extras disponibles :

| Commande | Usage |
|----------|-------|
| `pip install -e ".[sender]"` | sender Python uniquement |
| `pip install -e ".[receiver]"` | receiver CLI uniquement |
| `pip install -e ".[web]"` | web app + capture |
| `pip install -e ".[all]"` | sender + receiver + web |
| `pip install -e ".[dev]"` | stack complete + tests |

Pour un setup loopback sur un seul PC :

```bash
pip install -e ".[all]"
```

Si `cv2.imshow` ou les fenetres OpenCV echouent, installer la build non-headless :

```bash
pip install opencv-python --force-reinstall
```

## Demarrage rapide

1. Identifier l'index de la carte de capture.
2. Identifier l'ecran duplique vers cette capture.
3. Lancer la calibration.
4. Lancer le receiver puis le sender.

Commandes minimales :

```bash
hdmi-calibrate --profile balanced loopback 1
hdmi-recv 1 --profile balanced
hdmi-send monfichier.zip --mode fountain --profile balanced --screen 0
```

Pour le detail materiel complet, voir [docs/hardware-setup.md](docs/hardware-setup.md).

## Profils

| Profil | Resolution | FPS | Usage |
|--------|------------|-----|-------|
| `speed` | 1920x1080 | 240 | debit max, machine dediee |
| `balanced` | 1920x1080 | 60 | choix recommande pour loopback |
| `quality` | 3840x2160 | 30 | marge de signal plus large |

Sur un seul PC, commencer avec `balanced`.

## Protocoles

### Sequential

Frames ordonnees avec cycle START/DATA/END.

```bash
hdmi-send file.zip --mode sequential --profile balanced --redundancy 3 --screen 0
hdmi-recv 1 --mode sequential --profile balanced
```

### Fountain

Codage a effacement sans canal retour, robuste aux pertes de frames.

```bash
hdmi-send file.zip --mode fountain --profile balanced --screen 0
hdmi-recv 1 --mode fountain --profile balanced
```

Les budgets de performance du mode fountain sont maintenant verrouilles par tests.

## Interfaces

CLI publiques :
- `hdmi-send`
- `hdmi-recv`
- `hdmi-calibrate`
- `hdmi-bench`
- `hdmi-web`

Sender navigateur :

```bash
python tools/build_sender_html.py
python tools/build_sender_html.py --check
```

Le fichier genere est servi par l'interface web sur `/sender/app` et peut aussi etre utilise en standalone.

## Testing et quality gate

Commande locale canonique :

```powershell
powershell -ExecutionPolicy Bypass -File tools/run_quality_gate.ps1
```

Le gate execute :
- la suite `pytest` hors tests `hardware`
- les budgets fountain
- la verification `python tools/build_sender_html.py --check`
- un smoke benchmark `hdmi-bench --profile balanced --mode fountain --no-json`

Dans les environnements ou le test loopback OpenCV natif est instable, utiliser :

```powershell
powershell -ExecutionPolicy Bypass -File tools/run_quality_gate.ps1 -SkipNativeLoopback
```

Le detail des commandes et de la validation hardware est dans [docs/testing.md](docs/testing.md).

## Compatibilite

Les anciens chemins d'import (`hdmi_exfil.protocols`, `hdmi_exfil.config`, `hdmi_exfil.cli.*`, etc.) continuent de fonctionner via la couche `compat`. Pour identifier les imports legacy a migrer :

```bash
set HDMI_EXFIL_WARN_LEGACY_IMPORTS=1
```

## Depannage

Problemes courants :
- Receiver muet : verifier l'index de capture et refaire `hdmi-calibrate --profile balanced loopback <index>`.
- `hdmi-calibrate` rejette `--profile` : l'option doit etre placee avant le subcommand.
- FPS insuffisant en loopback : baisser le profil a `balanced` ou `quality`.
- SNR faible : verifier la duplication d'ecran vers l'Elgato et le cablage.

## Licence

Projet destine a des fins educatives et de recherche en securite autorisee uniquement.
