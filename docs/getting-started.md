# Installer et démarrer HDMI Transfer

[Retour à la présentation](../README.md)

## Variante Docker

Avec Docker démarré, lancer `docker compose up --build -d --wait`, puis ouvrir `http://localhost:5000`. Aucun Python local nécessaire. Les fichiers sont conservés dans un volume Docker. Voir le [guide Docker](docker.md) pour la capture sous Linux et les limites USB de Docker Desktop.

## Prérequis

- PC récepteur : Git, [uv](https://docs.astral.sh/uv/getting-started/installation/), pilote de la carte de capture et port USB adapté à cette carte.
- PC émetteur : navigateur récent et sortie HDMI ; Python n’est pas nécessaire pour `sender.html`.
- Liaison : câble HDMI et carte de capture HDMI vers USB. Deux sorties HDMI ne permettent pas une réception.
- Python : le projet demande Python 3.11 minimum ; uv utilise la version indiquée dans `.python-version` et peut la télécharger si nécessaire.

Installer uv sous Windows :

```powershell
winget install --id=astral-sh.uv -e
```

Sur macOS avec Homebrew :

```bash
brew install uv
```

Pour Linux et les autres méthodes, suivre les [instructions officielles uv](https://docs.astral.sh/uv/getting-started/installation/). Rouvrir le terminal après installation, puis vérifier `uv --version` et `git --version`.

## Accès au dépôt

Le dépôt est privé au moment de la rédaction. Se connecter avec un compte autorisé via Git Credential Manager, ou utiliser GitHub CLI :

```bash
gh auth login
gh repo clone Thunzyy/HDMI-transfer
cd HDMI-transfer
```

Avec Git déjà authentifié :

```bash
git clone https://github.com/Thunzyy/HDMI-transfer.git
cd HDMI-transfer
```

Le téléchargement ZIP depuis **Code → Download ZIP** dans GitHub convient aussi. Extraire tout le dossier, puis y ouvrir un terminal.

## Installer et lancer le récepteur

Sous Windows :

```powershell
.\start.bat
```

Sous Linux/macOS :

```bash
sh start.sh
```

Ou exécuter directement :

```bash
uv sync --locked --extra web
uv run --no-sync hdmi-web
```

Ouvrir [http://localhost:5000](http://localhost:5000). Les lanceurs travaillent depuis le dossier du projet, synchronisent l’environnement `.venv` avec `uv.lock` et transmettent les options au serveur. Ils s’arrêtent si l’installation échoue. Le premier lancement peut télécharger Python et les dépendances ; les suivants réutilisent l’environnement.

Le serveur écoute sur `127.0.0.1` par défaut. Les fichiers reçus sont stockés dans `received_files/` depuis le dossier de lancement. Garder le terminal ouvert ; `Ctrl+C` arrête le serveur.

Changer de port :

```powershell
.\start.bat --port 5001
```

Sous POSIX : `sh start.sh --port 5001`. Ouvrir alors `http://localhost:5001`.

## Deux PC sans réseau commun

```text
PC émetteur                  Carte de capture              PC récepteur
sender.html → sortie HDMI ──→ entrée HDMI → sortie USB ──→ interface Receive
```

1. Installer le récepteur et copier `sender.html` sur le PC émetteur à l’avance, par un moyen autorisé.
2. Brancher la carte et son câble USB. Utiliser le pilote et le port USB requis par le fabricant.
3. Dans les paramètres d’affichage du PC émetteur, repérer la sortie envoyée à la carte. Choisir une résolution de 1920 × 1080 à 60 Hz pour commencer.
4. Ouvrir `sender.html` localement, sélectionner un petit fichier de test et déplacer la fenêtre sur cette sortie. Le mode par défaut est **2-PC offline sender**, sans API récepteur.
5. Sur le récepteur, choisir la carte dans **Receive**. Sur les deux interfaces, conserver **Fountain**, **Balanced**, **2 bpc**. Garder **Preview quality: Low** côté réception.
6. Démarrer la réception avec **Start**, puis **Start transmission** sur l’émetteur. Accepter le plein écran si le navigateur le demande. Aucun autre contenu ne doit recouvrir le signal envoyé à la capture.
7. Attendre **Download** côté réception, enregistrer le fichier et arrêter l’émission. Pour valider une chaîne matérielle, comparer les empreintes SHA-256 de l’original et du fichier téléchargé.

Sous PowerShell :

```powershell
Get-FileHash .\monfichier.zip -Algorithm SHA256
```

Exécuter cette commande de chaque côté, sur les fichiers correspondants. Un test local dans le navigateur ne remplace pas cette validation de bout en bout.

## Deux PC sur un LAN de confiance

Pour charger le sender depuis le serveur du récepteur :

```powershell
.\start.bat --host 0.0.0.0
```

Sous POSIX : `sh start.sh --host 0.0.0.0`.

- Sur le récepteur : `http://localhost:5000/`.
- Sur le PC émetteur : `http://IP_DU_RECEPTEUR:5000/sender`.
- Sous Windows, `ipconfig` permet de trouver l’adresse IPv4 du récepteur.

`0.0.0.0` est l’adresse d’écoute, pas l’adresse à saisir dans le navigateur distant. Autoriser si nécessaire le port choisi sur le profil réseau privé du pare-feu. Le serveur expose réception, historique et téléchargements ; ne pas le publier directement sur Internet.

Le LAN sert l’interface. Le fichier à transférer est encodé dans le navigateur et transporté par HDMI. Pour un environnement réellement isolé du LAN, utiliser le HTML local de la section précédente.

## Tester avec un seul PC

Le test loopback demande toujours une sortie HDMI reliée à une capture :

1. Lancer le récepteur.
2. Ouvrir `http://localhost:5000/sender/test` pour activer explicitement l’API de test locale.
3. Afficher le sender sur la sortie reliée à la carte, puis recevoir depuis la même machine.

Le sender et le receiver partagent ici CPU/GPU : ce test peut être moins performant que deux PC. Voir [câblage et calibration](hardware-setup.md).

## Utilisation en ligne de commande

Installer les extras CLI dans chaque clone concerné :

```bash
uv sync --locked --extra all
```

Sur le récepteur :

```bash
uv run --no-sync hdmi-recv 0 --mode fountain --profile balanced --output received_files
```

Sur l’émetteur :

```bash
uv run --no-sync hdmi-send monfichier.zip --mode fountain --profile balanced --screen 1
```

`0` et `1` sont des exemples d’indices, à adapter à la capture et à l’écran. Le receiver accepte aussi `name:Elgato`, `raw:1` ou un chemin vidéo local. Lancer `--help` sur chaque commande pour les options complètes.

| Commande | Usage |
| --- | --- |
| `hdmi-web` | Interface web locale |
| `hdmi-send` / `hdmi-recv` | Émission / réception CLI |
| `hdmi-sender` / `hdmi-receiver` | Consoles interactives |
| `hdmi-calibrate` | Calibration du signal |
| `hdmi-bench` | Benchmark logiciel |

Les lanceurs installent seulement l’extra `web`. Après leur utilisation, relancer `uv sync --locked --extra all` pour les commandes CLI, ou `--extra dev` pour les outils de développement.

## Dépannage

| Symptôme | Vérification |
| --- | --- |
| `uv` introuvable | Installer uv puis rouvrir le terminal. |
| `Repository not found` | Vérifier l’accès au dépôt privé et le compte GitHub connecté. |
| Le port 5000 est occupé | Relancer avec `--port 5001` et utiliser cette adresse. |
| Aucune capture détectée | Vérifier USB/pilote, cliquer **Detect devices**, fermer OBS et les autres applications utilisant la carte. |
| Preview noire | Vérifier entrée/sortie HDMI, bon écran et bonne carte ; lancer le sender pour avoir un signal. |
| Images visibles mais décodage instable | Même protocole/profil/encodage des deux côtés ; revenir à Fountain + Balanced + 2 bpc, puis calibrer. |
| Speed ne change rien | Vérifier la fréquence réellement négociée par toute la chaîne, y compris la capture. |
| Le sender continue après réception | Le mode offline ne reçoit pas d’accusé de réception ; arrêter manuellement après **Download**. |
| `/sender/app` renvoie 404 | Conserver `sender.html` à la racine du clone ou le régénérer. |
| CLI ou pytest introuvable après un lancement web | Réinstaller l’extra `all` ou `dev` correspondant. |

## Développement et mise à jour

Sur un clone sans modifications locales :

```bash
git pull --ff-only
uv sync --locked --extra dev
uv run --no-sync python tools/build_sender_html.py --check
```

`sender.html` est généré depuis `src/interfaces/browser_sender/`. Pour le reconstruire :

```bash
uv run --no-sync python tools/build_sender_html.py
```

Sous Windows, exécuter le [contrôle qualité](testing.md) :

```powershell
uv run --no-sync powershell -ExecutionPolicy Bypass -File tools/run_quality_gate.ps1
```

Aucune validation matérielle Linux/macOS n’est revendiquée par ce guide. Les tests logiciels et les captures ne prouvent pas la compatibilité de chaque carte de capture.
