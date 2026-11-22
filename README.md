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
- **Des fichiers souvent 60 à 80 % moins volumineux** que les clips NVIDIA, sans perte de qualité visible : au lieu
  d'un débit fixe, l'encodage s'adapte à ce qui bouge à l'écran. Une minute en 1080p60 pèse en général 10 à 30 Mo.
- **Compression après chaque clip** (activée par défaut, onglet *General*) : le clip est réencodé en arrière-plan
  pour prendre moins de place, sans perte visible (souvent 2 à 3 fois plus petit pour un jeu qui bouge). Ça tourne en
  priorité basse pour ne pas gêner ton jeu, et l'original n'est remplacé qu'une fois la version compressée vérifiée.
  Il faut ffmpeg (`winget install Gyan.FFmpeg`).
- **Raccourci clavier** au choix (par défaut <kbd>Alt</kbd>+<kbd>F10</kbd>, comme NVIDIA ; par exemple
  <kbd>Alt</kbd>+<kbd>1</kbd>).
- **Petite notification « Clipped! »** dans le coin de l'écran, comme NVIDIA, qui ne vole pas le focus de ton jeu.
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

1. Télécharge `ClipCa-Setup-x.y.z.exe` dans les [Releases](../../releases/latest), ou directement la version
   compilée dans le dossier [`installateur/`](installateur/) de ce dépôt.
2. Lance-le. L'installateur n'est pas signé, donc Windows SmartScreen affiche un avertissement : clique sur
   **Informations complémentaires**, puis **Exécuter quand même**.
3. Il te faut [OBS Studio](https://obsproject.com). S'il n'est pas installé, l'application propose un bouton
   **Install OBS Studio** qui l'installe pour toi.

Les clips arrivent dans `Vidéos\Clips` (modifiable dans l'onglet *General*).

> **Astuce :** si tu utilises aussi le replay NVIDIA, désactive-le ou change le raccourci : NVIDIA utilise déjà
> <kbd>Alt</kbd>+<kbd>F10</kbd>.

> **Tu streames avec OBS ?** Ne ferme pas OBS : change de profil et de collection de scènes dans OBS. Quand OBS est
> sur un autre profil, le clipper se met en pause tout seul et reprend quand tu reviens sur « Clipper ».

## Envoyer un clip sur Discord

Un plugin [Vencord](https://github.com/Vendicated/Vencord) ajoute **Upload Last Clip** au menu <kbd>+</kbd> de
Discord. Il ouvre ton dernier clip, te laisse le couper (début / fin, facultatif) puis le compresse pour qu'il passe
sous la limite de Discord (10 Mo par défaut, réglable dans les paramètres du plugin : 50 avec Nitro Basic, 500 avec
Nitro). Si le clip (ou l'extrait coupé) tient déjà sous la limite, il est envoyé **sans perte**, sans réencodage ;
l'extrait coupé commence alors à l'image clé la plus proche, jusqu'à ~4 s avant le début choisi. Sinon il est réencodé, avec ta carte NVIDIA si elle peut (pilote 610 ou plus récent), sinon avec le processeur.

Prérequis : [Git](https://git-scm.com) et [Node.js](https://nodejs.org). Dans le dossier du dépôt :

```powershell
powershell -ExecutionPolicy Bypass -File discord\install.ps1
```

Le script installe ffmpeg et pnpm s'il les faut, télécharge Vencord dans `%USERPROFILE%\Apps\Vencord`, le compile
avec le plugin et l'injecte dans Discord (Discord se ferme pendant l'installation). Il crée aussi une tâche planifiée
**Keep Vencord** qui réinjecte Vencord après chaque mise à jour de Discord (à l'ouverture de session puis toutes les
5 minutes). Ne supprime pas le dossier Vencord : Discord le charge à chaque démarrage.

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
| `discord\uploadLastClip\` | Plugin Vencord : bouton, fenêtre de découpe (`index.tsx`), compression ffmpeg (`native.ts`) |
| `discord\install.ps1` | Installe Vencord avec le plugin et la tâche **Keep Vencord** |
| `discord\keep-vencord.ps1` | Réinjecte Vencord quand une mise à jour de Discord l'a enlevé |

L'application parle à OBS par son WebSocket intégré (activé automatiquement, protégé par mot de passe, en local).
Les réglages sont dans `%APPDATA%\ClipCa\settings.json` et le journal dans `clipper.log` au même endroit.

## Licence

[GPL-3.0](LICENSE). Composants utilisés :
[OBS Studio](https://obsproject.com) (GPL-2.0, installé à part),
[obsws-python](https://github.com/aatikturk/obsws-python) (GPL-3.0),
[Vosk](https://alphacephei.com/vosk/) et ses modèles (Apache-2.0),
[sounddevice](https://github.com/spatialaudio/python-sounddevice) (MIT),
[pystray](https://github.com/moses-palmer/pystray) (LGPL-3.0),
[Pillow](https://python-pillow.org) (MIT-CMU),
[Vencord](https://github.com/Vendicated/Vencord) (GPL-3.0, téléchargé à part),
[FFmpeg](https://ffmpeg.org) (GPL, installé à part).

Projet de fan, sans lien avec NVIDIA, OBS ou Discord.
