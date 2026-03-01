# PulseBeat (Flask + Jinja)

Application de streaming musical simple, style YouTube Music.

## Fonctionnalites

- comptes utilisateurs (inscription, connexion, deconnexion)
- confirmation de mot de passe a l'inscription
- ajout de chansons (URL externe ou upload local)
- visibilite des chansons:
  - `public`
  - `private` (partage avec utilisateurs selectionnes)
  - `unlisted` (non repertoriee)
- section `Mes chansons`
- page detail de chanson avec votes (j'aime / je n'aime pas / retirer reaction)
- commentaires publics + reponses + suppression de ses propres commentaires
- section `Gerer mon compte`:
  - changement de mot de passe (ancien mot de passe requis)
  - suppression de toutes ses chansons
  - suppression de compte avec option conserver/supprimer ses chansons
- playlists personnelles
- recherche + tri (`date`, `title`, `artist`) + pagination
- lecteur flottant persistant avec controles medias:
  - play/pause/next/previous
  - touches medias clavier (si support navigateur/OS)
- interface bilingue francais/anglais (preference sauvegardee en cookie `lang`)
- confirmation modal avant suppression de chanson
- interface responsive mobile avec menu hamburger
- zone admin dediee (interface separee) avec moderation utilisateurs/chansons/commentaires

## Structure

- `app.py`: app factory + enregistrement des blueprints
- `blueprints/accounts.py`
- `blueprints/main.py`
- `blueprints/songs.py`
- `blueprints/playlists.py`
- `templates/layout/`, `templates/accounts/`, `templates/main/`, `templates/playlists/`
- `static/js/player.js`, `static/js/app.js`, `static/css/styles.css`

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Copie ensuite l'exemple d'environnement:

```bash
copy .env.example .env
```

Puis renseigne `MONGO_URI` et `FLASK_SECRET_KEY` dans `.env`.

## Lancer

```bash
python app.py
```

Puis ouvre `http://127.0.0.1:5000`.

## MongoDB

Configuration via variables d'environnement:
- DB: `musicPlayer`
- collections: `users`, `songs`, `playlists`
- collections additionnelles: `song_votes`, `song_comments`
