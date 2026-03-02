# Tests

## Tests unitaires (pas de matériel requis)

```bash
pip install -r requirements-dev.txt
pytest
```

~300 tests couvrant : encode/decode séquentiel et fountain, PRNG, profils, calibration, capture threadée, tests property-based.

### Commandes utiles

```bash
pytest -v                          # sortie détaillée
pytest -k "not slow"               # exclure les tests lents (K>=500)
pytest tests/test_fountain.py -v   # un fichier spécifique
```

## Tests hardware (Elgato requis)

```bash
pytest -m hardware
```

Les tests marqués `@pytest.mark.hardware` nécessitent une Elgato connectée.

## Benchmark en mémoire

```bash
hdmi-bench --profile balanced --mode fountain --no-json
```

## Test loopback complet

```bash
# Terminal 1 : receiver
hdmi-recv 1 --profile balanced

# Terminal 2 : sender
hdmi-send monfichier.zip --mode fountain --profile balanced --screen 0
```

## Résultats validés

Testé sur Windows 11, Elgato 4K X, écran 1080p dupliqué :

| Test | Résultat |
|------|----------|
| Calibration loopback | SNR 60.0 dB (EXCELLENT) |
| Transfert 2.6 KB | SHA-256 OK, 0.14s |
| Transfert 50 KB | SHA-256 OK, 0.46s, ~110 KB/s |

## Fichiers de test

| Fichier | Contenu |
|---------|---------|
| `test_sequential.py` | Protocole séquentiel encode/decode |
| `test_fountain.py` | Protocole fountain, droplets |
| `test_fountain_3bpp.py` | Encodage 3 bits par bloc |
| `test_fountain_ge.py` | Élimination de Gauss (fallback) |
| `test_prng.py` | SplitMix32 déterminisme |
| `test_rsd.py` | Robust Soliton Distribution |
| `test_calibration.py` | Patterns de test, SNR |
| `test_threaded_capture.py` | Capture threadée ring buffer |
| `test_profiles.py` | Profils de résolution |
| `test_properties.py` | Tests property-based (hypothesis) |
