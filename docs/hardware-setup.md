# Setup materiel

## Scenario recommande

Le setup le plus simple pour developper et valider HDMI Transfer reste le loopback sur un seul PC :

```text
GPU ─── HDMI ──► ecran secondaire (sender)
 │
 └───── HDMI ──► Elgato 4K X ──► meme PC via USB
```

L'ecran secondaire et l'Elgato doivent recevoir le meme signal.

## Configuration Windows

1. Ouvrir `Parametres > Systeme > Affichage`
2. Reperer l'Elgato comme ecran supplementaire
3. Choisir `Dupliquer avec l'ecran secondaire`
4. Verifier que le sender s'affiche sur l'ecran duplique et que la capture le lit

## Trouver l'index de capture

```bash
ffmpeg -list_devices true -f dshow -i dummy 2>&1 | findstr "video"
```

Ou en Python :

```bash
python -c "
import cv2
for i in range(10):
    cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
    if cap.isOpened():
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f'Index {i}: {w}x{h}')
        cap.release()
"
```

## Trouver l'index du moniteur sender

```bash
python -c "
from hdmi_transfer.sender.display.monitors import get_monitors
for i, m in enumerate(get_monitors()):
    print(f'Monitor {i}: {m[\"width\"]}x{m[\"height\"]} at ({m[\"left\"]}, {m[\"top\"]})')
"
```

## Calibration

Toujours calibrer avant un transfert reel :

```bash
hdmi-calibrate --profile balanced loopback 1
```

Regle importante : `--profile` doit etre place avant le subcommand.

Interpretation du SNR :

| SNR | Qualite | Action |
|-----|---------|--------|
| > 30 dB | EXCELLENT | setup pret |
| 20-30 dB | GOOD | utilisable tel quel |
| 10-20 dB | FAIR | baisser le FPS ou passer en `quality` |
| < 10 dB | POOR | verifier duplication, cablage et source capture |

## Profils recommandes

| Profil | Resolution | FPS | Quand l'utiliser |
|--------|------------|-----|------------------|
| `balanced` | 1080p | 60 | point de depart par defaut |
| `quality` | 4K | 30 | si le signal est marginal |
| `speed` | 1080p | 240 | uniquement quand la machine tient la charge |

## Validation manuelle minimale

1. `hdmi-calibrate --profile balanced loopback <capture-index>`
2. `uv run hdmi-recv <capture-index> --profile balanced`
3. `uv run hdmi-send test.bin --mode sequential --profile balanced --screen <screen-index>`
4. `uv run hdmi-send test.bin --mode fountain --profile balanced --screen <screen-index>`
5. `uv run hdmi-web` puis verification de l'UI receiver et de `/sender`

## Symptomes frequents

- Le receiver ne voit rien : mauvais index de capture ou duplication d'ecran absente
- SNR bas : l'Elgato ne capture pas le bon affichage ou le mauvais cable est utilise
- Chute de FPS en loopback : sender et receiver se battent pour les memes ressources, revenir a `balanced`
- Decodage instable : verifier d'abord la calibration, ensuite la taille des blocs et le profil
