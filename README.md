# PulseBeat

Application de streaming musical en `Flask` + `Jinja`, inspirée de YouTube Music, avec lecteur flottant, comptes utilisateurs, playlists collaboratives, espace admin, i18n FR/EN et stockage MongoDB.

## Fonctionnalités

- Comptes utilisateurs locaux avec confirmation du mot de passe
- Vérification d'adresse e-mail obligatoire avant connexion
- Connexion Google OAuth
- Les comptes Google ne gèrent pas leur mot de passe dans PulseBeat : pas de changement de mot de passe local, pas de lockout lié aux mots de passe compromis
- Réinitialisation de mot de passe par e-mail
- Vérification des mots de passe compromis
- Changement de mot de passe et lock de sécurité si mot de passe compromis
- Ajout de chansons par URL ou upload (avec détection automatique des balises ID3)
- Lecture audio réelle avec lecteur flottant persistant entre les pages
- Contrôles lecture/pause/suivant/précédent
- Bouton `previous` type lecteur moderne : avant 5 secondes il revient à la chanson précédente, à partir de 5 secondes il redémarre la chanson courante
- Historique d'écoute
- Page de détail par chanson
- Like / dislike / commentaires / réponses
- Signalement de chansons et commentaires
- Playlists publiques, privées ou non répertoriées
- Collaborateurs de playlist
- Notifications e-mail lors des partages de playlist
- Recherche, suggestions, tri et pagination
- Zone admin séparée
- Interface bilingue français / anglais
- Pages d'erreur personnalisées

## Vérification d'e-mail

Les nouveaux comptes locaux, y compris l'admin principal créé au setup initial, doivent valider leur adresse e-mail avant de pouvoir se connecter.

Comportement actuel :
- un e-mail de vérification est envoyé à l'inscription
- la connexion est bloquée tant que l'e-mail n'est pas validé
- un bouton permet de renvoyer l'e-mail depuis la page de connexion
- les comptes existants avant cette mise à jour sont automatiquement marqués comme déjà vérifiés au démarrage de l'application
- les comptes Google sont considérés comme vérifiés automatiquement
- les comptes Google ne passent pas par la logique locale de fuite de mot de passe ni par le changement de mot de passe PulseBeat

## Lecteur audio

Le lecteur flottant persiste entre les pages et conserve son état en local.

Comportement notable :
- en lecture de playlist : modes `normal`, `shuffle` et `repeat one` disponibles
- hors playlist : lecture automatique avec recherche de recommandations
- bouton `previous` :
  - moins de 5 secondes de lecture : chanson précédente
  - 5 secondes ou plus : redémarrage de la chanson courante
- ce comportement s'applique aussi aux boutons média système compatibles (clavier, écouteurs, contrôles OS)

## Notifications e-mail

PulseBeat peut envoyer des e-mails pour :
- vérification de compte
- réinitialisation de mot de passe
- mot de passe compromis détecté
- partage de playlist

## Stack

- Python
- Flask
- Jinja2
- MongoDB / PyMongo
- JavaScript vanilla
- HTML / CSS

## Structure du projet

- `app.py` : création de l'application Flask, config, startup
- `extensions.py` : connexion MongoDB et collections
- `auth_helpers.py` : helpers auth, sécurité, mail, permissions
- `blueprints/accounts.py` : auth, setup initial, reset password, vérification e-mail, Google OAuth
- `blueprints/main.py` : accueil et navigation principale
- `blueprints/songs.py` : chansons, détails, votes, commentaires, signalements
- `blueprints/playlists.py` : playlists, collaborateurs, recherche, partage
- `blueprints/admin.py` : dashboard admin
- `templates/` : vues Jinja
- `static/js/player.js` : lecteur audio flottant
- `static/js/app.js` : interactions UI
- `static/css/styles.css` : styles

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python app.py
```

Puis ouvrir `http://127.0.0.1:5000`.

## Variables d'environnement

### Obligatoires

- `FLASK_SECRET_KEY`
- `MONGO_URI`

### MongoDB

Base utilisée : `musicPlayer`

Collections utilisées :
- `users`
- `songs`
- `playlists`
- `song_votes`
- `song_comments`
- `listening_history`
- `song_reports`
- `admin_audit`
- `system_status`
- `app_settings`

### SMTP

Nécessaire pour :
- vérification d'e-mail
- reset password
- notifications de partage

Variables :
- `MAIL_ENABLED=1`
- `MAIL_HOST=smtp.gmail.com`
- `MAIL_PORT=587`
- `MAIL_USERNAME=your_email@gmail.com`
- `MAIL_PASSWORD=your_app_password`
- `MAIL_USE_TLS=1`
- `MAIL_USE_SSL=0`
- `MAIL_FROM=PulseBeat <your_email@gmail.com>`
- `APP_BASE_URL=http://127.0.0.1:5000`
- `PASSWORD_RESET_TOKEN_MAX_AGE=3600`
- `PASSWORD_RESET_SALT=change-this-reset-salt`
- `EMAIL_VERIFICATION_TOKEN_MAX_AGE=86400`
- `EMAIL_VERIFICATION_SALT=change-this-email-verification-salt`

### Google OAuth

Optionnel.

Variables :
- `GOOGLE_CLIENT_ID=...`
- `GOOGLE_CLIENT_SECRET=...`
- `GOOGLE_REDIRECT_URI=http://127.0.0.1:5000/google-callback`

Configuration côté Google Cloud Console :
- `Authorized redirect URIs`
  - `http://127.0.0.1:5000/google-callback`
  - optionnellement aussi `http://localhost:5000/google-callback`
- `Authorized JavaScript origins`
  - `http://127.0.0.1:5000`
  - `http://localhost:5000`

Important :
- l'URI doit correspondre exactement, sinon Google retourne `redirect_uri_mismatch`
- si un e-mail existe déjà avec un compte local, la connexion Google est refusée pour cet e-mail

## Premier lancement

Si aucun admin principal n'existe dans la base, l'application bloque l'accès normal et affiche le setup initial.

Le compte admin principal créé lors de ce setup :
- devient `root admin`
- ne peut pas être supprimé
- doit lui aussi vérifier son e-mail avant la première connexion

## Développement

Vérifier la syntaxe Python :

```bash
python -m py_compile app.py auth_helpers.py blueprints\accounts.py blueprints\admin.py blueprints\songs.py blueprints\playlists.py i18n.py
```

## Comptes Google

Les comptes connectés via Google OAuth ont un comportement spécifique :
- l'adresse e-mail est considérée comme vérifiée par Google
- PulseBeat ne gère pas leur mot de passe
- le bloc de changement de mot de passe n'est pas affiché dans `Gérer mon compte`
- la vérification de mot de passe compromis et le lockout associé ne s'appliquent pas à ces comptes

## Sécurité

- ne jamais versionner le vrai fichier `.env`
- régénérer immédiatement tout secret exposé par erreur
- utiliser un vrai `FLASK_SECRET_KEY`
- utiliser un mot de passe d'application SMTP, pas le mot de passe principal de la boîte mail
