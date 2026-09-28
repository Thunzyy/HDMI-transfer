# Captures de HDMI Transfer

Ces PNG proviennent des pages réelles de l’application dans Chrome, sans retouche de l’interface ni injection de statistiques.

| Fichier | État présenté |
| --- | --- |
| `receiver.png` | Récepteur au repos, aucun périphérique de capture exposé. |
| `sender.png` | Sender offline avec `hello-hdmi.txt` chargé ; aucune transmission lancée. |
| `settings.png` | Page des réglages. |

Le serveur utilise un dossier temporaire vide et la détection matérielle est désactivée. Le script ne lit pas l’historique réel et n’ouvre aucune carte de capture. Ces images illustrent l’interface ; elles ne prouvent ni un transfert matériel réussi ni un débit mesuré.

La valeur « Throughput » du sender est une estimation calculée par l’interface, pas le résultat d’une mesure sur une carte HDMI.

## Régénération

Installer Chrome, puis depuis la racine du dépôt :

```bash
uv sync --locked --extra dev
uv run --no-sync python tools/capture_docs.py
```

Selenium Manager peut télécharger le pilote Chrome à la première exécution. Le script démarre un serveur local sur un port libre, ouvre un navigateur headless isolé, capture les trois pages et ferme ses ressources. Il échoue en cas d’erreur console sévère. Relire visuellement les captures avant de les publier.
