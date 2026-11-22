<p align="center"><img src="icon.png" width="96" alt="Icône de Clip Ça"></p>

<h1 align="center">Clip Ça</h1>

<p align="center">
  Un clipper pour Windows qui ne rate rien : il garde les dernières secondes de ton écran en mémoire
  et les enregistre quand tu appuies sur un raccourci ou quand tu dis <b>« clip ça »</b>.
</p>

---

## Pourquoi

Le replay instantané de NVIDIA, c'est pratique… quand il marche. Parfois il n'y a pas de son, parfois le replay se
désactive tout seul et tu rates le moment. Clip Ça s'appuie sur **OBS Studio**, qui est fiable, et le
surveille en permanence : si le replay s'arrête, il le relance dans les 5 secondes.

## Ce qu'il fait

- **Enregistre les X dernières secondes** (15 s à 5 min) avec le son du PC **et** ton micro.
- **Raccourci clavier** au choix (par défaut <kbd>Alt</kbd>+<kbd>F10</kbd>, comme NVIDIA).
- **Commande vocale** : dis « clip ça » (français) ou « clip that » (anglais). La reconnaissance tourne
  **hors ligne** sur ton PC, rien n'est envoyé sur internet.
- **Démarre avec Windows**, discret dans la barre des tâches (icône près de l'horloge).
- **Réglages** dans une fenêtre simple :
  - **Vidéo** : écran, résolution (native à 480p), images par seconde (30, 60, 120, 144), qualité, durée du clip.
  - **Audio** : sortie du son du PC, micro, volume, et effets micro : suppression de bruit, noise gate,
    compresseur, limiteur.
  - **Contrôles** : raccourci, phrases vocales, son de confirmation.
- **Choisit tout seul l'encodeur** selon ta carte graphique (NVIDIA, AMD, Intel, sinon le processeur). Si
  l'encodeur de la carte ne démarre pas, il passe sur le processeur.
- **Ne touche pas à ton OBS** : il utilise son propre profil « Clipper », tes scènes et réglages de stream restent
  comme ils sont.

## Installation

1. Télécharge `ClipCa-Setup-x.y.z.exe` dans les [Releases](../../releases/latest).
2. Lance-le. L'installateur n'est pas signé, donc Windows SmartScreen affiche un avertissement : clique sur
   **Informations complémentaires**, puis **Exécuter quand même**.
3. Il te faut [OBS Studio](https://obsproject.com). S'il n'est pas installé, l'application propose un bouton
   **Install OBS Studio** qui l'installe pour toi.

Les clips arrivent dans `Vidéos\Clips` (modifiable dans l'onglet *General*).

> **Astuce :** si tu utilises aussi le replay NVIDIA, désactive-le ou change le raccourci : NVIDIA utilise déjà
> <kbd>Alt</kbd>+<kbd>F10</kbd>.

> **Tu streames avec OBS ?** Ne ferme pas OBS : change de profil et de collection de scènes dans OBS. Quand OBS est
> sur un autre profil, le clipper se met en pause tout seul et reprend quand tu reviens sur « Clipper ».

## Compiler soi-même

Prérequis : Windows 10/11, [Python 3.12](https://www.python.org), [Inno Setup 6](https://jrsoftware.org/isinfo.php).

```powershell
git clone https://github.com/Rkyiel2/clip-ca.git
cd clip-ca
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\build.ps1
```

`build.ps1` télécharge les modèles vocaux (environ 80 Mo, une seule fois), compile l'application avec PyInstaller
dans `dist\` puis l'installateur dans `Output\`.

Pour lancer depuis le code sans compiler : `.\venv\Scripts\python.exe clipper_app.py`
(et `--selftest` pour vérifier que tout est en place).

## Comment ça marche

| Fichier | Rôle |
| --- | --- |
| `clipper_app.py` | Toute l'application : fenêtre, icône, raccourci, reconnaissance vocale, pilotage d'OBS |
| `build.ps1` | Télécharge les modèles, compile l'exe et l'installateur |
| `installer.iss` | Script de l'installateur (Inno Setup) |

L'application parle à OBS par son WebSocket intégré (activé automatiquement, protégé par mot de passe, en local).
Les réglages sont dans `%APPDATA%\ClipCa\settings.json` et le journal dans `clipper.log` au même endroit.

## Licence

[GPL-3.0](LICENSE). Composants utilisés :
[OBS Studio](https://obsproject.com) (GPL-2.0, installé à part),
[obsws-python](https://github.com/aatikturk/obsws-python) (GPL-3.0),
[Vosk](https://alphacephei.com/vosk/) et ses modèles (Apache-2.0),
[sounddevice](https://github.com/spatialaudio/python-sounddevice) (MIT),
[pystray](https://github.com/moses-palmer/pystray) (LGPL-3.0),
[Pillow](https://python-pillow.org) (MIT-CMU).

Projet de fan, sans lien avec NVIDIA ou OBS.
