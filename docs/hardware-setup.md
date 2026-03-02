# Setup matériel

## Setup un seul PC (loopback)

```
GPU ─── HDMI ──► Écran 2 (affichage sender)
 │
 └───── HDMI ──► Elgato 4K X (capture USB) ──► même PC
```

### Configuration Windows

1. **Paramètres > Affichage** : l'Elgato apparaît comme un écran
2. Sélectionner l'Elgato > **Dupliquer avec l'écran 2**
3. Le sender affiche sur l'écran 2, l'Elgato capture la même image

### Trouver l'index de l'Elgato

```bash
ffmpeg -list_devices true -f dshow -i dummy 2>&1 | findstr "video"
```

Ou via Python :

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

### Trouver l'index du moniteur

```bash
python -c "
from hdmi_exfil.display.monitors import get_monitors
for i, m in enumerate(get_monitors()):
    print(f'  Monitor {i}: {m[\"width\"]}x{m[\"height\"]} at ({m[\"left\"]}, {m[\"top\"]})')
"
```

## Calibration

Vérifier la qualité du signal avant un transfert :

```bash
hdmi-calibrate --profile balanced loopback 1
```

> `--profile` doit être placé **avant** le subcommand `loopback`.

| SNR | Qualité | Action |
|-----|---------|--------|
| > 30 dB | EXCELLENT | Prêt pour les transferts |
| 20-30 dB | GOOD | OK avec les paramètres par défaut |
| 10-20 dB | FAIR | Baisser le FPS ou utiliser `--profile quality` |
| < 10 dB | POOR | Vérifier le câble et la duplication d'écran |

## Configuration Elgato

| Profil | Résolution Elgato | FPS |
|--------|------------------|-----|
| `speed` | 1080p | 240 |
| `balanced` | 1080p | 60 |
| `quality` | 4K (3840x2160) | 30 |
