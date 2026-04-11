# Testing

## Gate local canonique

Le point d'entree unique pour valider la branche localement est :

```powershell
powershell -ExecutionPolicy Bypass -File tools/run_quality_gate.ps1
```

Le script execute dans l'ordre :

```text
pytest -m "not hardware"
pytest tests/test_fountain_overhead.py tests/perf/test_fountain_budget.py -v
python tools/build_sender_html.py --check
hdmi-bench --profile balanced --mode fountain --no-json
```

## Fallback local optionnel

Le gate complet passe maintenant avec `tests/test_loopback.py` inclus. Le switch `-SkipNativeLoopback` reste disponible uniquement comme secours local si une installation OpenCV est defectueuse sur un poste de dev particulier.

## Commandes ciblees utiles

```bash
pytest tests/contracts -v
pytest tests/test_send_session.py tests/test_receive_session.py -v
pytest tests/test_capture_manager.py tests/test_threaded_capture.py -v
pytest tests/test_web_app_factory.py tests/test_server_receive_file_api.py -v
pytest tests/test_compat_imports.py -v
pytest tests/test_sender_build.py tests/test_sender_html_magic.py -v
pytest tests/test_fountain_overhead.py tests/perf/test_fountain_budget.py -v
```

## Validation hardware

Le hardware n'entre pas dans la CI standard. Il doit etre valide manuellement sur une machine preparee :

1. `hdmi-calibrate --profile balanced loopback <capture-index>`
2. `hdmi-recv <capture-index> --profile balanced`
3. `hdmi-send <payload> --mode sequential --profile balanced --screen <screen-index>`
4. `hdmi-send <payload> --mode fountain --profile balanced --screen <screen-index>`
5. `hdmi-web`, puis verification des pages `/`, `/sender`, `/history` et `/settings`

## Ce que couvrent les tests

- Contrats protocole et compatibilite Python/browser
- Sessions shared send/receive
- Capture manager et backoff sur lecture ratee
- Interfaces web Flask et wrappers CLI
- Budgets de performance fountain
- Compatibilite des imports legacy
- Proprietes deterministes PRNG/RSD

## Regle de sortie

Une branche n'est pas prete a etre mergee tant que :
- `tools/run_quality_gate.ps1` ne passe pas
- `python tools/build_sender_html.py --check` ne passe pas
- les checks hardware manuels requis n'ont pas ete executes sur une machine equipee
