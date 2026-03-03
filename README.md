# HDMI Exfil

Transfert de fichiers via signal vidéo HDMI. Le sender encode des données dans des frames vidéo affichées à l'écran ; le receiver capture le flux via une carte de capture Elgato et décode le fichier original. Aucune trace réseau -- les données transitent uniquement par le câble HDMI.

Deux modes d'envoi :
- **Sender navigateur** (`sender.html`) -- zéro installation, ouvrir dans un navigateur et passer en plein écran
- **Sender Python** (`hdmi-send`) -- performance maximale, les deux protocoles

## Setup matériel (un seul PC)

Le projet fonctionne sur **un seul PC** avec une carte de capture en loopback :

```
  ┌─────────────────────────────────────────────────┐
  │                    PC unique                     │
  │                                                  │
  │   GPU ─── HDMI ──► Écran 2 (affichage sender)   │
  │    │                                             │
  │    └───── HDMI ──► Elgato 4K X (capture USB)     │
  │                        │                         │
  │                   hdmi-recv lit                   │
  │                   la capture                     │
  └─────────────────────────────────────────────────┘
```

| Composant | Détails |
|-----------|---------|
| **PC** | Windows/Linux avec GPU + 2 sorties HDMI (ou HDMI + DisplayPort) |
| **Elgato 4K X** | Carte de capture USB branchée sur le même PC |
| **Écran 2** | Moniteur secondaire -- l'affichage est **dupliqué** sur l'Elgato |
| **Câble HDMI** | Sortie GPU -> entrée Elgato (+ un câble vers l'écran 2) |

### Configuration Windows

1. Ouvrir **Paramètres > Système > Affichage**
2. L'Elgato apparaît comme un écran supplémentaire dans la liste
3. Sélectionner l'Elgato et choisir **« Dupliquer avec l'écran 2 »**
4. L'Elgato reçoit maintenant exactement la même image que l'écran 2
5. Le sender affiche ses frames sur l'écran 2 (`--screen 0` ou `--screen 1` selon votre config)
6. Le receiver lit le flux Elgato comme une caméra USB

## Installation

Nécessite **Python >= 3.11**.

```bash
git clone git@github.com:Thunzyy/HDMI_exfil.git
cd HDMI_exfil
```

Le package est découpé en extras -- installer uniquement ce dont vous avez besoin :

| Commande | Ce qu'elle installe | Quand l'utiliser |
|----------|---------------------|------------------|
| `pip install -e ".[sender]"` | numpy, numba, pygame-ce, screeninfo | PC qui **envoie** les fichiers |
| `pip install -e ".[receiver]"` | numpy, numba, opencv-python | PC qui **reçoit** les fichiers |
| `pip install -e ".[all]"` | sender + receiver | Un seul PC (loopback) |
| `pip install -e ".[dev]"` | all + pytest, hypothesis | Développement et tests |

**Loopback sur un seul PC (cas le plus courant) :**

```bash
pip install -e ".[all]"
```

**Important :** le package `opencv-python` (avec GUI) est nécessaire pour l'affichage des fenêtres debug. Si `cv2.imshow` échoue :

```bash
pip install opencv-python --force-reinstall
```

## Démarrage rapide (test loopback un seul PC)

### Étape 1 -- Trouver l'index de l'Elgato

Plusieurs caméras/webcams peuvent être branchées. Il faut trouver quel index correspond à l'Elgato :

```bash
python -c "
import cv2
for i in range(10):
    cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
    if cap.isOpened():
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f'  Index {i}: {w}x{h}')
        cap.release()
"
```

Exemple de sortie :

```
  Index 0: 1920x1080    <-- Iriun Webcam
  Index 1: 1920x1080    <-- Elgato 4K X
  Index 2: 1920x1080    <-- HD Webcam eMeet C960
  Index 3: 1920x1080    <-- Camera NVIDIA Broadcast
```

Pour identifier lequel est l'Elgato, utiliser ffmpeg :

```bash
ffmpeg -list_devices true -f dshow -i dummy 2>&1 | findstr "video"
```

Retenir l'index de l'Elgato (ex: `1`).

### Étape 2 -- Identifier l'écran dupliqué vers l'Elgato

```bash
python -c "
from hdmi_exfil.sender.display.monitors import get_monitors
for i, m in enumerate(get_monitors()):
    print(f'  Monitor {i}: {m[\"width\"]}x{m[\"height\"]} at ({m[\"left\"]}, {m[\"top\"]})')
"
```

Exemple de sortie :

```
  Monitor 0: 1920x1080 at (2560, 0)    <-- Écran 2 (dupliqué vers Elgato)
  Monitor 1: 2560x1080 at (0, 0)       <-- Écran principal (ultrawide)
```

Retenir l'index du moniteur dupliqué (ex: `0`).

### Étape 3 -- Calibration loopback

Vérifier que l'Elgato capture bien le signal de l'écran dupliqué :

```bash
hdmi-calibrate --profile balanced loopback 1
```

> **Attention** : `--profile` doit être placé **avant** le subcommand `loopback`.

Résultat attendu :

```
Calibration Results:
  Alignment offset: (x, y) pixels
  SNR: 60.0 dB
  Signal quality: EXCELLENT
```

Si le SNR est < 20 dB, l'Elgato ne capture pas le bon écran (vérifier la duplication dans les paramètres d'affichage).

### Étape 4 -- Transférer un fichier

Ouvrir **deux terminaux** :

**Terminal 1 -- Receiver :**

```bash
hdmi-recv 1 --profile balanced
```

(remplacer `1` par l'index Elgato trouvé à l'étape 1)

**Terminal 2 -- Sender :**

```bash
hdmi-send monfichier.zip --mode fountain --profile balanced --screen 0
```

(remplacer `0` par l'index moniteur trouvé à l'étape 2)

Le sender affiche les frames encodées sur l'écran 2, l'Elgato les capture, et le receiver décode le fichier.

### Étape 5 -- Vérification

Le receiver affiche la progression en temps réel :

```
Progress: 100% (5/5) | 109.7 KB/s | ETA: 0:00
Download complete!
SHA-256 verified OK.
Saved to received_files/monfichier.zip
```

Le fichier reçu est dans `received_files/` avec vérification SHA-256.

## Profils de résolution

| Profil | Résolution | FPS | Débit estimé | Usage |
|--------|-----------|-----|-------------|-------|
| `speed` (défaut) | 1920x1080 | 240 | ~2.8 MB/s | Débit maximum |
| `balanced` | 1920x1080 | 60 | ~0.7 MB/s | Fiabilité stable, recommandé pour les tests |
| `quality` | 3840x2160 | 30 | ~1.4 MB/s | Meilleure marge de signal |

> **Pour les tests sur un seul PC**, commencer avec `balanced` (60 FPS). Le profil `speed` (240 FPS) peut saturer le pipeline si le sender et le receiver tournent sur le même CPU/GPU.

## Protocoles

### Sequential

Frames ordonnées avec cycle START/DATA/END. Fiable sur connexion stable.

```bash
hdmi-send file.zip --mode sequential --profile balanced --redundancy 3 --screen 0
hdmi-recv 1 --mode sequential --profile balanced
```

### Fountain (LT Codes)

Codage à effacement sans retour. Le sender émet des droplets XOR en continu ; le receiver collecte jusqu'à reconstitution complète. Pas de canal retour nécessaire -- parfait pour le HDMI unidirectionnel. Tolère les frames perdues.

```bash
hdmi-send file.zip --mode fountain --profile balanced --screen 0
hdmi-recv 1 --mode fountain --profile balanced
```

## Référence CLI

### hdmi-send

```
hdmi-send <fichier> [OPTIONS]

Options:
  --mode {sequential,fountain}        Protocole (défaut: sequential)
  --profile {speed,balanced,quality}  Profil de résolution
  --renderer {pygame,cv2}             Backend d'affichage (défaut: pygame)
  --fps INT                           FPS cible (override le profil)
  --redundancy INT                    Répétition par frame, sequential uniquement (défaut: 1)
  --fountain-redundancy FLOAT         Arrêt après K*N droplets (ex: 1.05 = 5% overhead)
  --screen INT                        Index du moniteur (défaut: 0)
```

### hdmi-recv

```
hdmi-recv <source> [OPTIONS]

Arguments:
  source                              Index caméra (0, 1, 2...) ou chemin vidéo

Options:
  --mode {auto,sequential,fountain}   Protocole (défaut: auto-detect)
  --profile {speed,balanced,quality}  Doit correspondre au profil du sender
  --output DIR                        Dossier de sortie (défaut: received_files)
  --threaded / --no-threaded          Capture threadée avec ring buffer (défaut: on)
  --buffer-size INT                   Taille du ring buffer (défaut: 16 frames)
```

### hdmi-calibrate

Tester la qualité du signal avant un transfert.

> **Attention** : `--profile` doit être placé **avant** le subcommand (`send`, `recv`, `loopback`).

```
hdmi-calibrate [--profile {speed,balanced,quality}] send [--renderer {cv2,pygame}]
hdmi-calibrate [--profile {speed,balanced,quality}] recv <source> [--frames INT]
hdmi-calibrate [--profile {speed,balanced,quality}] loopback <source> [--frames INT]
```

Exemples :

```bash
# Afficher le pattern de calibration
hdmi-calibrate --profile balanced send

# Capturer et analyser depuis l'Elgato (index 1)
hdmi-calibrate --profile balanced recv 1

# Loopback complet : afficher + capturer + analyser
hdmi-calibrate --profile balanced loopback 1
```

Résultats : offset d'alignement, SNR en dB, qualité (EXCELLENT > 30 dB, GOOD > 20, FAIR > 10, POOR).

### hdmi-bench

Benchmark de débit en mémoire (pas de matériel requis).

```bash
hdmi-bench --profile balanced --mode fountain --no-json
```

```
Options:
  --profile {speed,balanced,quality}   Défaut: speed
  --mode {sequential,fountain}         Défaut: fountain
  --size INT                           Taille du payload en KB (défaut: 100)
  --duration FLOAT                     Max secondes pour fountain (défaut: 10)
  --no-json                            Sortie lisible (pas JSON)
```

## Encodage

Chaque bloc de 8x8 pixels encode **3 bits** (1 bit par canal RGB). Canal noir = 0, canal blanc = 255. Une frame 1920x1080 contient 240x135 = 32 400 blocs = 97 200 bits = **12 150 octets** par frame.

Les headers consomment 17 octets (sequential) ou 12 octets (fountain), laissant 12 133 ou 12 138 octets de payload par frame.

## Architecture

Le code est organisé en trois sous-packages : **core** (pas de dépendance hardware), **sender** (pygame-ce) et **receiver** (opencv-python).

```
src/hdmi_exfil/
  core/                  Partagé -- numpy + numba uniquement
    config.py            Constantes, ResolutionProfile, PROFILES
    constants.json       Source de vérité partagée (Python + JS)
    prng.py              SplitMix32 PRNG (déterministe cross-language)
    protocols/
      base.py            EncodingProtocol ABC
      sequential.py      Protocole séquentiel (START/DATA/END)
      fountain.py        Fountain LT codes + FountainDecoder
      degree.py          Robust Soliton Distribution
      xor_ops.py         Opérations XOR optimisées
    capture/
      sampler.py         Frame -> grille de blocs
      threaded.py        ThreadedCapture avec ring buffer
    file_handling/
      reader.py          Lecture fichier/dossier (auto-zip)
      writer.py          Écriture fichier de sortie
      metadata.py        Nom, taille, SHA-256
    cli/
      progress.py        ProgressTracker (vitesse, ETA)
      benchmark.py       Point d'entrée hdmi-bench

  sender/                Dépend de pygame-ce, screeninfo
    display/
      renderer.py        PygameRenderer (SDL2)
      test_patterns.py   Patterns de calibration + analyse SNR
      monitors.py        Détection multi-moniteur
    cli/
      send.py            Point d'entrée hdmi-send

  receiver/              Dépend de opencv-python
    capture/
      source.py          CaptureSource (DirectShow / V4L2 / AVFoundation)
    cli/
      receive.py         Point d'entrée hdmi-recv
      calibrate.py       Point d'entrée hdmi-calibrate

sender.html              Sender navigateur fountain (zéro installation)
```

Les anciens chemins d'import (`hdmi_exfil.protocols`, `hdmi_exfil.config`, etc.) restent fonctionnels via des shims de compatibilité.

## Dépannage

**Le receiver ne reçoit rien :** Vérifier l'index de la capture card. Lancer `hdmi-calibrate --profile balanced loopback 1` pour tester le signal.

**`hdmi-calibrate: error: unrecognized arguments` :** Le `--profile` doit être placé **avant** le subcommand. Écrire `hdmi-calibrate --profile balanced loopback 1` et non `hdmi-calibrate loopback 1 --profile balanced`.

**`cv2.imshow` plante / "The function is not implemented" :** Vous avez `opencv-python-headless`. Installer la version complète : `pip install opencv-python --force-reinstall`.

**L'Elgato n'apparaît pas :** Installer les drivers Elgato (4K Capture Utility). Sous Windows, l'Elgato doit apparaître dans le Gestionnaire de périphériques > Caméras.

**Transferts corrompus :** Baisser le FPS (`--fps 30`), utiliser `--profile quality`, augmenter `--redundancy`, ou passer en mode fountain qui tolère les pertes de frames.

**FPS faible en loopback :** Sur un seul PC le sender et le receiver partagent le CPU/GPU. Utiliser `--profile balanced` (60 FPS) au lieu de `speed` (240 FPS). Fermer les autres applications gourmandes.

**Le sender ne s'affiche pas sur le bon écran :** Vérifier l'index `--screen`. Lancer le script de l'étape 2 pour voir les moniteurs détectés et leurs index.

**SNR < 20 dB à la calibration :** L'Elgato ne capture pas le bon écran. Vérifier que l'affichage est bien dupliqué dans les paramètres Windows. Si le SNR est entre 10-20 dB, essayer `--profile quality` (blocs plus gros).

## Tests validés

### Tests unitaires (pas de matériel requis)

```bash
pip install -e ".[dev]"   # installe tout + pytest + hypothesis
pytest                    # 170 tests pass
hdmi-bench --no-json      # benchmark en mémoire
```

### Tests loopback hardware (Elgato requis)

Résultats réels obtenus sur un seul PC (Windows 11, Elgato 4K X, écran 1080p dupliqué) :

| Test | Taille | Résultat | Détails |
|------|--------|----------|---------|
| Calibration loopback | -- | SNR 60.0 dB (EXCELLENT) | Pattern checkerboard 1080p balanced |
| Transfert fountain | 2.6 KB | SHA-256 OK | K=1, 2 droplets, 0.14s |
| Transfert fountain | 50 KB | SHA-256 OK | K=5, 7 droplets, 0.46s, ~110 KB/s |

## Licence

Ce projet est destiné à des fins éducatives et de recherche en sécurité autorisée uniquement.
