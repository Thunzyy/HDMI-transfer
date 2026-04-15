# HDMI Transfer

Transfert de fichiers par signal video HDMI. Le sender affiche des frames encodees sur une sortie ecran, le receiver lit ce signal via une carte de capture et reconstruit le fichier sans utiliser le reseau pour les donnees.

Le projet est maintenant organise directement sous `src/`:

```text
src/
  adapters/
  application/
  core/
  domain/
  interfaces/
  receiver/
  sender/
  web/
```

Le nom logique du package reste `hdmi_transfer`, mais les sources ne vivent plus dans un sous-dossier `src/hdmi_transfer/`.

## Quick Start

Setup recommande: `2 PC`.

- `PC sender`: machine qui affiche les frames HDMI
- `PC receiver`: machine avec la carte de capture

### 1. Installer

Sur le receiver:

```bash
git clone git@github.com:Thunzyy/HDMI-transfer.git
cd HDMI-transfer
uv sync --extra web
```

Si tu veux aussi les outils CLI sender/receiver sur la meme machine:

```bash
uv sync --extra all
```

Pour un environnement de dev complet:

```bash
uv sync --extra dev
```

`uv` cree automatiquement un environnement local dans `.venv/`.

### 2. Lancer l'interface web

Sur le receiver:

```bash
uv run hdmi-web --host 0.0.0.0 --port 5000
```

Ouvre ensuite:

- receiver UI: `http://localhost:5000/`
- sender UI integree locale: `http://localhost:5000/sender`

Pour un vrai setup `2 PC` isole, `/sender` est maintenant le chemin par defaut. Ouvre cette page depuis le PC sender sur l'hote web du receiver. Elle charge le sender en mode `offline` par defaut, sans API receiver active. Le mode test `1 PC` reste separe.

### 3. Regler les bons defaults

Pour la plupart des setups `2 PC`, laisse ces valeurs:

- `Protocol`: `Fountain`
- `Profile`: `Balanced`
- `Encoding`: `2 bpc`
- `Preview quality`: `Low`

Ces choix sont les plus robustes sur du materiel varie. Passe en `Speed` uniquement si la sortie HDMI du sender est sur un chemin dedie `120/144/240 Hz`.

### 4. Recevoir un fichier

Sur le receiver:

1. Ouvre `Receive`
2. Selectionne la carte de capture HDMI
3. Verifie que la preview montre bien le signal attendu
4. Clique `Start`

Sur le sender:

1. Ouvre `http://<IP_DU_RECEIVER>:5000/sender` sur le PC sender
2. Charge un fichier
3. Mets la fenetre sender en plein ecran sur la sortie HDMI envoyee a la carte de capture
4. Clique `Start transmission`

Quand le transfer est termine, le bouton `Download` apparait cote receiver.

## Variante CLI

### Receiver

```bash
uv run hdmi-recv 0 --mode fountain --profile balanced --output received_files
```

`0` peut aussi etre remplace par:

- `name:Elgato`
- `raw:1`
- un chemin video local

### Sender

```bash
uv run hdmi-send monfichier.zip --mode fountain --profile balanced --screen 1
```

Commence en `balanced`. Monte en `speed` seulement si le chemin HDMI reel tient plus de `60 Hz`.

## Sender navigateur genere

`sender.html` est un artefact genere, pas un fichier a maintenir a la main.

```bash
uv run python tools/build_sender_html.py
uv run python tools/build_sender_html.py --check
```

Le sender standalone est aussi servi par le web sur `/sender/app`.

- `sender.html` ou `/sender/app`: mode sender standalone, `offline` par defaut
- `/sender`: wrapper web par defaut pour le setup `2 PC`, sans API receiver active
- `/sender/test`: wrapper explicite pour le setup de test `1 PC`, avec API locale active

## Profils

| Profil | Resolution | FPS cible | Usage |
|--------|------------|-----------|-------|
| `speed` | 1920x1080 | 240 | chemin HDMI dedie haut refresh |
| `balanced` | 1920x1080 | 60 | meilleur choix par defaut |
| `quality` | 3840x2160 | 30 | priorite a la marge de signal |

## Interfaces disponibles

- `hdmi-send`
- `hdmi-recv`
- `hdmi-calibrate`
- `hdmi-bench`
- `hdmi-web`

## Testing

Gate local:

```powershell
uv run powershell -ExecutionPolicy Bypass -File tools/run_quality_gate.ps1
```

Verification des assets sender:

```bash
uv run python tools/build_sender_html.py --check
```

## Documentation

- [Architecture](docs/architecture.md)
- [Migration](docs/migration.md)
- [Testing](docs/testing.md)
- [Setup materiel](docs/hardware-setup.md)

## Depannage rapide

- Ecran noir dans la preview: verifier que la bonne carte de capture est selectionnee et que la sortie HDMI du sender lui est bien envoyee.
- `Speed` n'accelere rien: le chemin HDMI reel est probablement encore a `60 Hz`.
- Decode instable: revenir a `Balanced + Fountain + 2 bpc`.
- Materiel faible cote receiver: baisser la `Preview quality`.

## Commandes `uv` utiles

```bash
uv sync --extra web
uv sync --extra all
uv sync --extra dev
uv run hdmi-web --host 0.0.0.0 --port 5000
uv run pytest
```

## Licence

Projet destine a des fins educatives et de recherche en securite autorisee uniquement.
