# PulseBeat

Plateforme de streaming musical hybride en `Flask` + `Jinja`, inspirée de YouTube Music, avec lecteur flottant persistant, comptes utilisateurs, playlists collaboratives, recommandations, espace admin, i18n FR/EN et stockage MongoDB.

## Fonctionnalités

- Comptes utilisateurs locaux avec confirmation du mot de passe
- Vérification d'adresse e-mail obligatoire avant connexion
- Connexion Google OAuth
- Les comptes Google ne gèrent pas leur mot de passe dans PulseBeat : pas de changement de mot de passe local, pas de lockout lié aux mots de passe compromis
- Authentification 2 facteurs (2FA) optionnelle pour les comptes locaux : code par courriel, application d'authentification (TOTP), ou les deux avec méthode favorite
- Activation/désactivation de chaque méthode 2FA confirmée par courriel puis mot de passe
- Courriel principal modifiable et courriel de secours vérifiable pour récupérer l'accès au compte
- Réinitialisation / récupération de mot de passe par courriel principal, courriel de secours, 2FA courriel ou 2FA TOTP
- Avertissement à l'inscription pour e-mail temporaire avec confirmation explicite avant création du compte
- Vérification des mots de passe compromis
- Verrouillage progressif de connexion par adresse e-mail après échecs répétés (6 tentatives), avec durée doublée à chaque cycle
- Envoi automatique d'un e-mail de déverrouillage après verrouillage, avec lien sécurisé de déverrouillage + connexion
- Changement de mot de passe et lock de sécurité si mot de passe compromis
- Changement du nom d'utilisateur depuis `Gérer mon compte`, avec validation JavaScript en direct + validation serveur
- Option `Se souvenir de moi` à la connexion, avec durée de session prolongée et avertissement de sécurité explicite
- Invalidation globale des sessions après changement ou réinitialisation de mot de passe
- Protection anti-vol de session par appareil de confiance + approbation par courriel des nouveaux appareils
- Invalidation des sessions suspectes si un cookie semble rejoué depuis un autre environnement
- Écran de blocage de session suspecte renforcé avec bandeau d'avertissement visuel, animation d'alerte et tentative de son d'avertissement au chargement
- Watchdog d'intégrité MongoDB : tentative d'auto-récupération des documents invalides, suppression en dernier recours, alerte admins et fallback `422`
- Détection de stockage saturé avec erreur `507`, verrouillage global de la plateforme jusqu'au redémarrage, et blocage du setup tant qu'un espace minimal n'est pas disponible
- Résilience runtime avec gestion des erreurs `503`, `408` et `429` : limp mode, surcharge latched, timeout adaptatif selon la qualité réseau perçue, watchdog anti-robot et honeypot de formulaires
- Ajout de chansons par URL ou upload (avec détection automatique des balises ID3)
- Stockage optionnel des chansons publiques dans MongoDB GridFS avec cache local reconstructible côté serveur
- Enrichissement automatique artiste/genre après upload via recherche en ligne
- Détection automatique des sous-titres (métadonnées audio + recherche multi-sources en ligne)
- Normalisation titre/artiste pour améliorer le matching des sous-titres
- Support des fichiers de sous-titres `.lrc` et `.txt` en fallback manuel
- Traitement local des fichiers de sous-titres avec modal bloquante et feedback visuel clair
- Synchronisation timeline activée pour les fichiers `.lrc` avec timestamps; mode non synchronisé pour `.txt` ou `.lrc` incomplet
- Relance manuelle de la recherche de sous-titres depuis le formulaire d'ajout
- Lecture audio réelle avec lecteur flottant persistant entre les pages
- Contrôles lecture/pause/suivant/précédent
- Éditeur de file d'attente (réordonner, retirer, lire un élément précis)
- Option de crossfade entre chansons
- Option de normalisation de volume côté lecteur
- Cache serveur intelligent : audio YouTube récemment écouté + cache JSON des données publiques coûteuses
- Lecteur avec vues `mini`, `normale` et `plein écran`
- Recaps PulseBeat à la demande + recap annuel automatique avec notification interne et export JSON/CSV
- Gestures tactiles mobile : ouverture/fermeture du menu hamburger par glissement, navigation recap par swipe, et transitions mini lecteur / plein écran par geste
- Bouton `previous` type lecteur moderne : avant 5 secondes il revient à la chanson précédente, à partir de 5 secondes il redémarre la chanson courante
- Anti-superposition audio multi-onglets (modal de garde audio + blocage de lecture sur onglet récent tant que non confirmé)
- Si une chanson est référencée en base mais introuvable sur le serveur, le lecteur affiche une erreur générique avec code HTTP (ex. 404) et suggère de passer à la suivante
- Historique d'écoute
- Page de détail par chanson
- Like / dislike / commentaires / réponses
- Signalement de chansons et commentaires
- Modération automatique des termes vulgaires sur chansons, playlists et commentaires (avertissements + ban automatique au 3e strike)
- Alertes admin (sécurité/modération) masquables individuellement avec bouton `X`, persistance par admin et annulation rapide (toast 10s)
- Playlists publiques, privées ou non répertoriées
- Collaborateurs de playlist
- Réorganisation persistante des chansons dans une playlist par glisser-déposer pour le propriétaire et les collaborateurs
- Partage externe des chansons/playlists publiques ou non répertoriées (copie de lien + plateformes)
- Préférences utilisateur pour exclure des chansons ou artistes des recommandations
- Recommandations v2 équilibrées (mix préférences personnelles + populaires + découverte)
- Statistiques créateur dans `Gérer mon compte` (écoutes, likes/dislikes, top chansons)
- Abonnements publics aux créateurs avec désabonnement, compteur d'abonnés et notifications internes de nouvelles publications via la cloche PulseBeat
- Panneau de notifications de publication responsive et utilisable sur mobile
- Détection des doublons audio à l'upload via fingerprint SHA-256
- Export des données de compte en JSON et CSV
- Synchronisation de bibliothèque externe YouTube avec import de playlists (fonctionnelle), avec lecture partielle de certaines pistes selon les limites YouTube/Google
- Workers persistants d'import YouTube : reprise automatique après redémarrage du serveur, suivi d'état dans `Gérer mon compte`, pause/reprise/annulation par playlist
- Notifications e-mail lors des partages de playlist
- Recherche, suggestions, tri et pagination (incluant recherche insensible à la casse dans les paroles)
- Profils publics utilisateurs avec chansons et playlists accessibles selon les permissions
- Validations JavaScript en direct sur les formulaires, avec validation serveur conservée
- Blocage complet du site si JavaScript est désactivé
- Sources JavaScript conservées lisibles côté projet, avec bundles obfusqués servis au navigateur
- Unicité des `username` et `email` garantie côté serveur et par index MongoDB
- Zone admin séparée
- Réinitialisation complète de PulseBeat par le root admin, avec confirmation par mot de passe + courriel avant destruction des données
- Interface bilingue français / anglais
- Pages d'erreur personnalisées

## Upload, modification et détection

### Upload d'une chanson

- L'utilisateur peut publier via URL audio directe ou upload de fichier (`.mp3`, `.wav`, `.ogg`, `.m4a`).
- Si un fichier audio est uploadé, PulseBeat lit d'abord les métadonnées ID3 locales.
- Ordre de priorité au remplissage automatique :
  - `title`, `artist`, `genre` depuis les tags ID3 quand disponibles
  - enrichissement Internet de `artist`/`genre` à partir du `title` si des champs restent vides
- Si des paroles sont trouvées dans les métadonnées audio (ID3 `USLT`/`SYLT`), elles sont utilisées immédiatement.
- Si aucune parole n'est trouvée en métadonnées, la recherche online est lancée avec fallback multi-sources.

### Modification d'une chanson

- Le propriétaire peut modifier `title`, `artist`, `genre`.
- Le fichier audio source n'est pas remplacé en édition.
- Pour les chansons sans sous-titres, un bouton de détection permet de relancer la récupération automatique.
- Si l'automatique échoue, l'utilisateur peut ajouter un fichier de sous-titres (`.lrc` ou `.txt`).

### Pipeline de détection des sous-titres

Étapes générales :

1. Vérification locale des métadonnées du fichier audio (ID3) en priorité.
2. Si rien n'est trouvé : recherche online avec plusieurs fallback API/sources.
3. Si toujours rien : fallback manuel via fichier de sous-titres (`.lrc`/`.txt`).

Recherche online (ordre de fallback actuel) :

- `lrclib` endpoint `/api/get`
- `lrclib` endpoint `/api/search` avec variantes normalisées du titre
- `lrclib` endpoint `/api/search?q=...` (requête combinée artiste+titre)
- `Lyricsify` (scraping de la page normalisée artiste/titre)
- `lyrics.ovh`

### Détection artiste/genre (après upload)

- Si `artist` ou `genre` manque après lecture des tags ID3, PulseBeat interroge une source online de métadonnées musicales (iTunes Search API).
- Le meilleur résultat est sélectionné par similarité de titre.
- Les champs manquants sont complétés automatiquement sans écraser les champs déjà fournis.

### Fichiers `.lrc` et `.txt` (manuel)

- `.lrc` : traitement local avec validation des timestamps.
- `.txt` : traitement local en paroles non synchronisées.
- Le modal de traitement affiche l'étape en cours et un message final indique si la synchronisation est active ou non.
- Quand un fichier de sous-titres manuel est sélectionné, PulseBeat traite le fichier localement (sans relancer une recherche lyrics online depuis cet upload).

### Détection des doublons audio (SHA-256)

La détection anti-doublon est basée sur le contenu binaire audio, pas sur le nom du fichier ni le titre saisi.

Workflow précis :

1. après upload, le serveur calcule un hash `SHA-256` du fichier (`audio_fingerprint`)
2. il recherche une chanson existante avec le même fingerprint
3. si trouvée :
   - l'upload est annulé
   - le fichier temporaire est supprimé
   - un message utilisateur indique quelle chanson existante correspond
4. si non trouvée, la chanson est créée normalement

Effet pratique : une même piste audio ne peut pas être uploadée deux fois, même avec un titre/artiste différent.

## Stockage audio durable en base (GridFS + cache local)

### Objectif

- Cette fonctionnalité permet, pour certaines chansons publiques, de conserver une copie durable du fichier audio directement dans MongoDB Atlas via `GridFS`.
- Le but est de simplifier une migration de serveur ou une reconstruction après perte du dossier `static/uploads/`, tout en évitant de lire les gros blobs audio directement depuis MongoDB à chaque écoute.

### Activation admin et contrôle d'accès

- La fonctionnalité se configure depuis la zone admin dans le bloc `Stockage audio en base`.
- Deux niveaux de contrôle existent :
  - activation globale ou non de la fonctionnalité
  - liste d'utilisateurs autorisés à voir cette option pendant l'upload
- Les administrateurs gardent toujours l'accès à l'option, même s'ils ne figurent pas explicitement dans la liste.
- Si la fonctionnalité est désactivée ou si l'utilisateur n'est pas autorisé, le formulaire d'ajout reste sur le mode classique `stockage serveur`.

### Expérience utilisateur pendant l'upload

- Lorsqu'un utilisateur autorisé ajoute une chanson publique avec un vrai fichier audio, PulseBeat affiche un modal de choix juste avant l'envoi final.
- Deux options sont proposées :
  - `Stocker sur le serveur`
  - `Stocker dans la base`
- L'interface explique aussi que :
  - le stockage serveur reste l'option recommandée si l'utilisateur n'est pas certain
  - le stockage en base peut être un peu plus lent au premier chargement dans le lecteur
- Cette demande de choix n'apparaît pas :
  - pour les chansons privées
  - pour les chansons non répertoriées
  - pour les ajouts par URL seule
  - pour les utilisateurs non autorisés

### Modèle de stockage

- PulseBeat n'enregistre pas le MP3 directement dans le document `songs`.
- À la place, le fichier est envoyé dans un bucket `GridFS` (`audio_files`) et la chanson garde des métadonnées de pilotage :
  - `storage_mode`
  - `gridfs_file_id`
  - `audio_cache_status`
  - `original_file_name`
  - `audio_content_type`
  - `audio_file_size`
- Le mode `database` signifie que MongoDB devient la source durable de vérité.
- Le fichier local peut néanmoins rester présent sur le serveur comme cache de lecture.

### Lecture et reconstruction automatique

- Le lecteur ne lit pas en continu depuis GridFS.
- Il essaie toujours d'abord de lire la version locale du fichier dans `static/uploads/`.
- Si le fichier local manque mais qu'une copie `GridFS` existe :
  - la route de stream tente une reconstruction vers le serveur
  - le lecteur peut aussi déclencher une route dédiée de récupération en cas de `404`
- Une fois le fichier reconstruit localement :
  - les lectures suivantes passent de nouveau par le serveur
  - MongoDB n'est plus sollicité pour chaque lecture

### Comportement du lecteur en cas de `404`

- Si une chanson uploadée retourne `404` :
  - PulseBeat vérifie si une copie de secours existe dans GridFS
  - si oui, il tente de reconstruire le fichier local
  - si la reconstruction est terminée, le lecteur relance automatiquement la lecture
  - sinon, il affiche un message indiquant que la reconstruction est en cours et suggère d'attendre ou de passer à la chanson suivante
- Si aucune copie en base n'existe, le comportement `404` normal est conservé.

### Robustesse et optimisation MongoDB

- `GridFS` est utilisé au lieu d'un champ binaire direct dans `songs` pour éviter :
  - la limite MongoDB de `16 MB` par document
  - les documents trop lourds
  - les lectures massives répétées côté cluster Atlas
- Les chansons conservent aussi un état de cache (`audio_cache_status`) pour éviter des reconstructions concurrentes inutiles.
- Des index dédiés existent sur :
  - `storage_mode`
  - `gridfs_file_id`
  - `audio_cache_status`
- En cas d'échec du stockage GridFS lors d'un upload, PulseBeat bascule proprement en stockage serveur avec un message d'avertissement, au lieu de perdre la chanson.

## Cache serveur intelligent (audio YouTube + données publiques)

### Objectif

- PulseBeat ajoute maintenant une couche de cache serveur pour réduire :
  - les appels MongoDB coûteux sur Atlas free tier
  - les téléchargements répétés côté YouTube
  - le temps de rendu de certaines pages publiques très consultées
- Le cache reste borné en taille et en nombre de fichiers pour éviter qu'il grossisse sans limite sur le serveur.

### Cache audio YouTube

- Lorsqu'une chanson YouTube commence réellement à être lue :
  - PulseBeat planifie un téléchargement audio local en arrière-plan
  - le téléchargement utilise `yt-dlp`
  - le fichier est stocké dans le cache serveur local, pas dans MongoDB
- Tant que ce cache n'existe pas, la lecture continue en mode YouTube classique.
- Dès que le cache audio local est disponible :
  - `serialize_song()` bascule automatiquement la chanson en mode `audio`
  - le lecteur peut alors passer par la route de stream locale au lieu de l'iframe YouTube

### Stratégie de lecture hybride

- Pour une chanson `external` YouTube :
  - si un fichier audio cache existe déjà : PulseBeat sert directement le fichier local
  - sinon : PulseBeat lance ou réutilise un worker de cache audio, puis redirige vers la source YouTube comme avant
- Cela garde une lecture immédiate pour l'utilisateur, tout en préparant les prochaines écoutes pour qu'elles soient plus rapides et moins dépendantes de YouTube.

### Contrôle de taille du cache audio

- Le cache YouTube applique une politique simple de type `LRU` :
  - on met à jour la date d'accès quand un fichier est relu
  - les fichiers les moins récemment utilisés sont supprimés en premier quand les limites sont dépassées
- Deux limites bornent le cache :
  - taille totale max (`YOUTUBE_AUDIO_CACHE_MAX_BYTES`)
  - nombre max de fichiers (`YOUTUBE_AUDIO_CACHE_MAX_FILES`)

### Cache JSON des données publiques

- PulseBeat met aussi en cache certaines données texte/JSON coûteuses :
  - profils publics (vue publique de base)
  - pages de playlists publiques non collaboratives
  - agrégats de chansons populaires utilisés dans les recommandations
- Le cache JSON est stocké dans le dossier serveur de cache et non dans la base.

### Invalidation intelligente

- Le cache n'est pas seulement basé sur un `TTL`.
- PulseBeat conserve aussi des `versions` locales par groupe de données.
- Quand une donnée importante change, PulseBeat invalide la bonne famille de cache :
  - ajout / édition / suppression / changement de disponibilité d'une chanson
  - ajout / suppression / réorganisation / renommage / changement de visibilité d'une playlist
  - abonnement / désabonnement à un créateur
  - changement de nom d'utilisateur
- Pour les agrégats très volatils comme la popularité globale des chansons, PulseBeat privilégie un `TTL` court au lieu d'une invalidation à chaque écoute, pour ne pas recréer de charge Mongo inutile.

### Profils publics

- La vue publique de base d'un profil est cacheable côté serveur.
- Pour un visiteur anonyme :
  - PulseBeat peut servir directement cette version mise en cache
- Pour un utilisateur connecté non propriétaire :
  - PulseBeat réutilise la base publique mise en cache
  - puis rajoute au besoin les éléments privés explicitement partagés avec lui
- Pour le propriétaire du profil :
  - PulseBeat garde un rendu live complet, car il voit plus d'informations (gestion du compte, abonnés, contenus non publics)

### Playlists publiques

- Quand une playlist est publique et que le visiteur n'est ni propriétaire ni collaborateur, PulseBeat peut réutiliser une vue cacheable de la playlist.
- Si certains éléments privés de la playlist sont partagés avec l'utilisateur connecté, ils sont réinjectés dynamiquement dans le rendu live pour ne pas casser les permissions.
- Si une recherche interne est active sur la playlist, PulseBeat repasse sur un calcul live pour éviter les ambiguïtés de pagination/filtrage.

### Robustesse

- Si le cache est absent, expiré ou corrompu :
  - PulseBeat retombe automatiquement sur le calcul live
  - puis régénère le cache proprement
- Si un téléchargement YouTube échoue :
  - la lecture ne casse pas
  - le lecteur garde la stratégie YouTube normale
- Le cache est donc une optimisation opportuniste, jamais une dépendance bloquante.

## Recherche de chansons et autocomplétion

PulseBeat utilise une logique de recherche unifiée pour les principales barres de recherche liées aux chansons. Le but n'est pas d'exiger une correspondance exacte caractère par caractère, mais de retrouver un morceau de manière tolérante et naturelle, même si l'utilisateur tape sans accents, avec une ponctuation différente, ou seulement un fragment de texte.

### Barres de recherche concernées

Cette logique s'applique aux zones suivantes :

- barre de recherche principale de l'accueil
- recherche interne dans une playlist (`songs_q`)
- suggestions d'autocomplétion globales des chansons
- suggestions d'autocomplétion limitées à une playlist
- champ de sélection d'une chanson à ajouter dans une playlist

### Propriétés de chanson utilisées

Quand PulseBeat cherche un morceau, il compare la requête contre ces propriétés :

- `title`
- `artist`
- `genre`
- `lyrics_text`

Cela signifie qu'une chanson peut être trouvée :

- parce que le mot figure dans le titre
- parce qu'il figure dans le nom de l'artiste
- parce qu'il figure dans le genre
- ou simplement parce qu'il apparaît dans les paroles / sous-titres textuels

Effet pratique :

- un utilisateur peut retrouver une chanson en tapant un bout de refrain, même s'il ne connaît ni le titre ni l'artiste

### Règles de matching

PulseBeat n'utilise pas un simple test `texte exact == requête`. Le matching suit plusieurs règles de tolérance :

- recherche **insensible à la casse**
  - `party`, `Party` et `PARTY` reviennent au même
- recherche **insensible aux accents et à beaucoup de variantes latines**
  - `ete` matche `été`
  - `francois` matche `François`
  - `garcon` matche `garçon`
- recherche **tolérante aux séparateurs et à une partie de la ponctuation**
  - les espaces, tirets, apostrophes, underscores et ponctuation courante sont traités de manière souple
  - par exemple `cafe noir` peut retrouver `café-noir`
- recherche **partielle**
  - il n'est pas nécessaire de taper toute la valeur complète
  - un fragment pertinent dans un champ suffit à faire ressortir la chanson

En interne, PulseBeat transforme la requête en motif de recherche souple, puis l'applique aux propriétés ci-dessus aussi bien dans MongoDB que dans les filtres Python utilisés sur certaines vues paginées.

### Différence entre recherche libre et sélection guidée

PulseBeat a deux usages différents de l'autocomplétion :

- **recherche libre**
  - accueil
  - recherche interne d'une playlist
  - l'utilisateur tape une requête, voit des suggestions, puis peut :
    - cliquer une suggestion
    - ou simplement appuyer sur `Entrée` pour soumettre le formulaire
  - `Entrée` ne force plus la première suggestion
- **sélection guidée**
  - ajout d'une chanson dans une playlist
  - ici, le champ sert à sélectionner une chanson précise
  - l'utilisateur doit choisir une suggestion valide pour que l'identifiant caché (`song_id`) soit renseigné correctement

### Recherche de l'accueil

La recherche de l'accueil est la plus large :

- elle applique les critères sur tout le catalogue visible par l'utilisateur
- elle respecte les permissions habituelles :
  - chansons publiques
  - chansons non répertoriées ou privées seulement si elles sont réellement accessibles à l'utilisateur courant
- si l'utilisateur clique une suggestion précise, PulseBeat transmet aussi son `song_id`
- dans ce cas, le backend garde cette chanson explicitement dans la requête, même si la requête texte a évolué légèrement

### Recherche dans une playlist

La recherche interne d'une playlist fonctionne différemment :

- elle ne cherche que parmi les chansons déjà présentes dans cette playlist
- les suggestions sont donc limitées à cette playlist
- les permissions sont toujours respectées
- si une recherche est active, PulseBeat désactive volontairement certaines actions comme le réordonnancement drag-and-drop, afin d'éviter de manipuler une vue filtrée partielle

### Suggestions d'autocomplétion

Les suggestions servent à accélérer la navigation, mais elles ne remplacent pas la recherche libre :

- elles utilisent les mêmes propriétés (`title`, `artist`, `genre`, `lyrics_text`)
- elles sont elles aussi insensibles à la casse et aux accents
- elles sont limitées en nombre pour rester rapides et légères
- cliquer une suggestion remplit le champ avec un libellé lisible du type `Titre - Artiste`

### Pourquoi PulseBeat n'a pas besoin d'un match exact 1 pour 1

PulseBeat essaie de refléter la façon réelle dont un humain cherche une chanson :

- on se souvient parfois d'un refrain, pas du titre
- on tape souvent sans accents
- on oublie la ponctuation exacte
- on écrit parfois seulement une partie du nom

Au lieu d'imposer une égalité stricte, PulseBeat :

- normalise la requête
- élargit certaines lettres à leurs variantes accentuées
- neutralise une partie des séparateurs
- lance ensuite une recherche partielle sur plusieurs champs

Le résultat est plus permissif, plus naturel, et beaucoup plus proche d'un usage réel qu'un simple matching exact.

## Vérification d'e-mail

Les nouveaux comptes locaux, y compris l'admin principal créé au setup initial, doivent valider leur adresse e-mail avant de pouvoir se connecter.

Comportement actuel :
- un e-mail de vérification est envoyé à l'inscription
- la connexion est bloquée tant que l'e-mail n'est pas validé
- un bouton permet de renvoyer l'e-mail depuis la page de connexion
- les comptes existants avant cette mise à jour sont automatiquement marqués comme déjà vérifiés au démarrage de l'application
- les comptes Google sont considérés comme vérifiés automatiquement
- les comptes Google ne passent pas par la logique locale de fuite de mot de passe ni par le changement de mot de passe PulseBeat
- les demandes de réinitialisation de mot de passe sur un compte Google sont refusées côté serveur avec une erreur générique `501` (sans divulguer le provider)

## Auth et sessions

- Après 6 échecs de connexion pour une adresse e-mail existante, la connexion est verrouillée pendant 10 minutes pour cette adresse.
- Si ce seuil est atteint à nouveau, la durée est doublée (10, 20, 40, 80, ... minutes).
- Dès qu'un verrouillage est appliqué, un e-mail de déverrouillage est envoyé automatiquement à l'adresse concernée.
- Le lien de déverrouillage valide le verrou, reconnecte l'utilisateur automatiquement, puis réinitialise le compteur de lockout.
- Une connexion réussie avec les bons identifiants réinitialise le compteur et le niveau de verrouillage.
- Après un changement de mot de passe ou une réinitialisation, toutes les sessions existantes sont invalidées globalement ; une reconnexion est requise sur tous les appareils.

## Système anti-vol de compte et de session

PulseBeat protège désormais les sessions avec une logique de **sessions liées à l'appareil** plutôt qu'une simple confiance implicite dans le cookie Flask.

Objectif :
- compliquer l'exploitation d'un cookie de session volé
- éviter les faux positifs trop agressifs liés à une géolocalisation IP stricte
- garder une expérience utilisateur raisonnable sur un appareil habituel

### Principe général

Quand un utilisateur se connecte avec succès :

1. PulseBeat crée ou lit un **cookie d'appareil dédié** (`pulsebeat_device_id` par défaut).
2. Le serveur calcule une empreinte liée à cet appareil :
   - hash du cookie d'appareil
   - signature coarse du navigateur (`OS + navigateur`)
   - préfixe IP approximatif pour contexte
3. La session authentifiée est enregistrée côté serveur dans le document utilisateur.
4. L'appareil est enregistré comme **appareil de confiance**.

Ensuite, à chaque requête authentifiée :
- le serveur vérifie que l'`active_session_id` de la session Flask existe toujours côté base
- il vérifie aussi que cette session est utilisée depuis le **même appareil logique**
- si ce n'est plus le cas, la session est considérée comme suspecte et est invalidée immédiatement

### Données suivies côté serveur

Chaque utilisateur peut maintenant contenir :

- `trusted_devices`
  - liste des appareils de confiance
  - chaque entrée contient notamment :
    - `device_hash`
    - `ua_hash`
    - `label`
    - `last_ip_prefix`
    - dates `first_seen_at` / `last_seen_at`

- `active_sessions`
  - sessions en cours autorisées
  - chaque entrée contient notamment :
    - `session_id`
    - `device_hash`
    - `ua_hash`
    - `label`
    - `last_ip_prefix`
    - dates `created_at` / `last_seen_at`

- `pending_device_approvals`
  - demandes d'approbation de nouveaux appareils encore valides

### Premier appareil vs nouvel appareil

Cas 1 : premier appareil connu d'un compte
- si aucun appareil de confiance n'existe encore, l'appareil courant devient automatiquement approuvé
- l'utilisateur n'est pas bloqué

Cas 2 : appareil déjà connu
- si l'appareil courant correspond à un appareil de confiance, la connexion continue normalement

Cas 3 : nouvel appareil inconnu
- la connexion est **bloquée**
- PulseBeat envoie un **courriel d'approbation d'appareil**
- tant que l'utilisateur n'a pas cliqué sur ce lien, la connexion reste refusée sur cet appareil

### Courriel d'approbation d'appareil

Quand un nouvel appareil est détecté :

- un lien signé temporaire est généré
- ce lien expire selon `DEVICE_APPROVAL_TOKEN_MAX_AGE`
- le courriel contient un résumé du contexte détecté, par exemple :
  - type d'appareil / navigateur
  - préfixe IP approximatif

Si l'utilisateur clique sur le lien :
- l'appareil est ajouté aux `trusted_devices`
- la demande est retirée de `pending_device_approvals`
- si le clic se fait depuis le même appareil :
  - la connexion est autorisée directement
  - si la 2FA est activée, PulseBeat envoie ensuite le code 2FA comme d'habitude
- si le clic se fait depuis un autre appareil :
  - l'appareil est tout de même approuvé
  - l'utilisateur doit ensuite revenir se connecter normalement sur cet appareil

### Détection d'une session suspecte

Si une session active existe côté serveur mais qu'elle est utilisée depuis un environnement différent :

- PulseBeat invalide immédiatement cette session
- l'entrée correspondante est retirée des `active_sessions`
- la session Flask locale est vidée
- un courriel d'alerte est envoyé au propriétaire du compte
- l'utilisateur qui tente d'utiliser cette session reçoit une page de blocage dédiée

Ce comportement couvre notamment :
- réutilisation d'un cookie de session sur un autre appareil
- mismatch entre appareil attendu et appareil réellement utilisé
- session active qui n'existe plus côté base

### Message affiché en cas de session bloquée

Quand une session est jugée suspecte :

- côté HTML :
  - PulseBeat affiche une page de blocage pleine page
  - un bandeau d'**avertissement** rouge très visible est affiché en haut du message
  - ce bandeau inclut une animation visuelle d'alerte pour attirer immédiatement l'attention
  - une tentative de son d'alerte est jouée au chargement de la page si le navigateur l'autorise
  - le message explique que l'utilisation semble illégitime
  - il rappelle que des actions punitives peuvent s'appliquer en cas d'abus
- côté AJAX / API :
  - PulseBeat renvoie une réponse JSON propre avec code `403`

### Interaction avec les autres mécanismes de sécurité

Le système anti-vol de session fonctionne avec les autres protections existantes :

- **2FA**
  - la 2FA reste demandée après validation de l'identifiant/mot de passe
  - si un nouvel appareil doit être approuvé, l'approbation d'appareil arrive d'abord
  - ensuite, si la 2FA est active, le code 2FA est demandé

- **Changement ou réinitialisation de mot de passe**
  - toutes les `active_sessions` sont vidées
  - les anciennes sessions deviennent invalides partout
  - l'utilisateur doit se reconnecter

- **Comptes Google**
  - ils passent aussi par la logique d'appareil de confiance pour la session
  - en revanche, la gestion des mots de passe compromis reste désactivée pour eux

### Limites connues

Cette protection augmente nettement la difficulté d'exploitation d'un cookie volé, mais il faut rester réaliste :

- si un attaquant dérobe à la fois le cookie de session **et** le cookie d'appareil depuis le même navigateur compromis, la détection devient plus difficile
- le système privilégie un bon compromis entre sécurité et UX, pas une preuve absolue d'identité matérielle

En pratique, cela reste beaucoup plus robuste qu'une session Flask classique non liée à un appareil.

## Abonnements créateurs et notifications internes

PulseBeat permet de suivre les créateurs de musique publiant sur la plateforme, avec un modèle proche de YouTube mais volontairement plus simple et moins intrusif.

### S'abonner à un créateur

Depuis la page publique d'un utilisateur :

- un utilisateur connecté peut cliquer sur `S'abonner`
- il peut activer ou non l'option `Activer les notifications de publication`
- l'abonnement est **public**
- le créateur voit donc son nombre total d'abonnés publiquement sur son profil

Comportement :

- si l'utilisateur n'était pas encore abonné, PulseBeat crée l'abonnement
- s'il était déjà abonné, le même formulaire sert à mettre à jour la préférence `notifications_enabled`
- le désabonnement est disponible via un bouton `Se désabonner` sur ce même profil

### Se désabonner

PulseBeat gère explicitement le désabonnement :

- le bouton `Se désabonner` supprime l'abonnement du compte courant pour ce créateur
- l'opération est idempotente : si l'abonnement n'existe déjà plus, l'application reste cohérente
- après désabonnement :
  - le compteur public d'abonnés diminue
  - plus aucune nouvelle notification de publication n'est créée pour ce créateur

### Visibilité publique des abonnements

Contrairement à YouTube, les abonnements sont considérés comme publics dans PulseBeat :

- tous les visiteurs voient le **nombre** d'abonnés d'un créateur
- seul le propriétaire du profil peut voir la **liste nominative** de ses abonnés

Quand le créateur visite sa propre page publique :

- un bouton ouvre une modale listant les abonnés
- chaque ligne contient un lien cliquable vers le profil public de l'abonné
- cette liste n'est jamais affichée aux autres visiteurs, qui ne voient que le compteur

### Notifications de publication

Les notifications liées aux abonnements restent **internes à PulseBeat** :

- elles ne sont pas envoyées par courriel
- elles apparaissent dans la cloche du header
- elles sont consultables dans un panneau non bloquant

Une notification est créée lorsqu'un créateur publie :

- une **nouvelle chanson publique**
- une **nouvelle playlist publique**
- ou lorsqu'une playlist existante devient publique

Chaque notification contient :

- le nom du créateur
- un lien vers le profil public du créateur
- le titre du contenu publié
- un lien direct vers la chanson ou la playlist

### Lecture et état des notifications

Dans le header :

- la cloche affiche un compteur de notifications non lues
- l'ouverture du panneau marque les notifications affichées comme lues
- si aucune notification n'existe, PulseBeat affiche un état vide propre
- sur mobile, le panneau s'ouvre comme une surface flottante dédiée au-dessus de l'interface, pour éviter qu'il soit masqué par le menu hamburger
- le panneau reste refermable explicitement et utilisable au tactile

### Résistance aux courses MongoDB

Les flux d'abonnement ont été durcis pour éviter les incohérences sous accès concurrents :

- l'abonnement utilise un **upsert atomique** basé sur le couple `(creator_id, subscriber_id)`
- un index unique MongoDB empêche les doublons même si deux clics concurrents arrivent presque en même temps
- le désabonnement utilise une suppression idempotente
- la création des notifications de publication supporte déjà les doublons concurrents via index unique + gestion des erreurs de duplication

Si une écriture Mongo échoue malgré tout :

- PulseBeat essaie d'abord de récupérer proprement l'opération
- si la récupération échoue, l'utilisateur reçoit un message clair
- la page d'erreur globale ne doit apparaître qu'en dernier recours, si la gestion locale ne suffit pas

## Gestion des courriels du compte et récupération

### Courriel principal

Un compte local peut maintenant changer son **courriel principal** depuis `Gérer mon compte`.

Flux :
1. l'utilisateur saisit son nouveau courriel principal
2. PulseBeat vérifie côté client puis côté serveur que l'adresse n'est pas déjà utilisée
3. un courriel de confirmation signé est envoyé à la nouvelle adresse
4. après clic sur le lien, le nouveau courriel devient le courriel principal du compte

Garanties :
- un courriel déjà utilisé comme courriel principal, courriel secondaire ou changement en attente est refusé
- les collisions tardives MongoDB sont rattrapées et renvoyées en message utilisateur propre
- les comptes Google ne passent pas par le changement de mot de passe local, mais gardent leur logique de contact cohérente

### Courriel de secours

PulseBeat permet aussi d'enregistrer un **courriel de secours** vérifié, destiné à la récupération de compte.

Comportement :
- le courriel de secours se configure dans `Gérer mon compte`
- il doit être confirmé par lien signé avant d'être considéré comme valide
- il peut être retiré explicitement par l'utilisateur
- il est traité comme une adresse sensible : unicité contrôlée côté serveur

Sécurité spécifique :
- les courriels temporaires restent tolérés pour le courriel principal
- ils sont en revanche **bloqués** pour le courriel de secours
- la détection est faite côté JavaScript et confirmée côté serveur

### Incitation à configurer une méthode de récupération

Après la première connexion d'un nouveau compte local, PulseBeat affiche un message dédié invitant l'utilisateur à configurer au moins une solution de récupération :
- 2FA par courriel
- 2FA par application d'authentification
- ou courriel de secours vérifié

En parallèle, le dashboard admin signale clairement les comptes locaux n'ayant ni 2FA active ni courriel de secours vérifié.

### Mot de passe oublié / récupération d'accès

La récupération d'accès supporte désormais plusieurs méthodes selon ce que le compte a configuré :

- courriel principal
- courriel de secours
- 2FA par courriel
- 2FA par application d'authentification (TOTP)

Comportement général :
1. l'utilisateur lance `Mot de passe oublié` avec son courriel ou son nom d'utilisateur
2. PulseBeat calcule les méthodes réellement disponibles pour ce compte
3. l'utilisateur choisit la méthode souhaitée
4. une preuve de possession est demandée
5. après validation, PulseBeat autorise la définition d'un nouveau mot de passe

Important : les comptes Google ne peuvent pas utiliser la réinitialisation locale de mot de passe. PulseBeat répond alors par une erreur générique côté serveur sans révéler publiquement le provider du compte.

## Authentification 2 facteurs (2FA)

### Vue d'ensemble

PulseBeat propose une 2FA **optionnelle** pour les comptes locaux (non Google).

Méthodes disponibles :
- **courriel** : un code à 6 chiffres envoyé au courriel principal
- **application d'authentification** : code TOTP compatible Google Authenticator / Microsoft Authenticator
- **mode combiné** : les deux méthodes peuvent être activées en même temps

L'utilisateur peut définir une **méthode favorite**. C'est celle que PulseBeat demandera par défaut au login, avec un bouton pour basculer temporairement vers l'autre méthode si elle est aussi configurée.

Important :
- les comptes Google ne peuvent pas activer la 2FA PulseBeat (la sécurité 2FA est gérée côté Google)
- la 2FA locale s'applique uniquement après une authentification primaire correcte (`courriel ou username + mot de passe`)

### Activation / désactivation de la 2FA courriel

Flux :
1. l'utilisateur ouvre `Gérer mon compte` > `Authentification 2 facteurs`
2. il demande l'activation ou la désactivation de la méthode courriel
3. PulseBeat envoie un **lien signé temporaire** de confirmation
4. l'utilisateur ouvre ce lien
5. le système demande le **mot de passe actuel** pour finaliser
6. la méthode courriel devient active ou inactive

Cela évite une bascule 2FA silencieuse si la session web est déjà ouverte sur un poste compromis.

### Activation de la 2FA par application d'authentification

Flux :
1. dans `Gérer mon compte`, l'utilisateur démarre le setup `Application d'authentification`
2. PulseBeat génère un secret TOTP temporaire
3. l'interface affiche :
   - la **clé secrète**
   - l'**URI de provisioning**
4. l'utilisateur ajoute ce secret dans son application d'authentification
5. il saisit ensuite un code TOTP valide pour confirmer l'appairage
6. la méthode TOTP est activée et peut devenir la méthode favorite

Si l'utilisateur abandonne en cours de route, il peut annuler le setup. Le secret de setup en attente expire automatiquement après `TWO_FACTOR_TOTP_PENDING_MAX_AGE`.

### Désactivation de la 2FA par application

La désactivation suit un flux direct depuis `Gérer mon compte`.
Si la méthode TOTP était la favorite et que la méthode courriel reste active, PulseBeat bascule automatiquement la méthode favorite vers `courriel`.

### Technique 2FA utilisée

#### Méthode courriel

- code OTP numérique à `6` chiffres
- code généré côté serveur via `secrets.randbelow(...)`
- le code n'est **pas stocké en clair** en session :
  - PulseBeat stocke un hash SHA-256 basé sur `user_id + code + FLASK_SECRET_KEY`
- durée de validité configurable via `TWO_FACTOR_CODE_MAX_AGE`
- possibilité de renvoyer un nouveau code depuis l'écran de challenge

#### Méthode TOTP

- secret compatible RFC TOTP via `pyotp`
- codes générés côté application d'authentification de l'utilisateur
- vérification serveur avec fenêtre de tolérance courte (`valid_window=1`)
- aucun code TOTP ponctuel n'est stocké côté PulseBeat

### Mauvais code / trop de tentatives

Le challenge 2FA applique les mêmes garde-fous quelle que soit la méthode choisie :

- chaque code invalide incrémente un compteur en session
- un message explicite indique le nombre de tentatives restantes
- limite stricte : `6` erreurs
- à la limite atteinte :
  - la session de challenge 2FA est invalidée
  - retour à la page de connexion
  - il faut recommencer le login complet
- si le code expire, même comportement

### Méthode favorite et fallback

Quand les deux méthodes sont actives :
- PulseBeat demande d'abord la méthode favorite
- l'utilisateur peut cliquer pour basculer vers l'autre méthode disponible
- ce basculement est **temporaire** pour le challenge en cours et ne change pas forcément la préférence enregistrée

Effet pratique :
- la 2FA reste flexible si le courriel tarde à arriver
- ou si l'application d'authentification n'est pas immédiatement accessible

## Réorganisation persistante des playlists

Les chansons d'une playlist peuvent maintenant être réordonnées par **glisser-déposer** directement dans la page de détail de la playlist.

Qui peut réordonner :
- le propriétaire de la playlist
- les collaborateurs autorisés

Comportement :
- le drag and drop s'effectue directement dans la liste de chansons
- le nouvel ordre est envoyé au serveur puis persisté en base MongoDB
- l'ordre est conservé pour toutes les lectures futures de cette playlist

Limite volontaire :
- quand une recherche interne de playlist est active, le drag and drop est désactivé
- cela évite de réordonner une vue filtrée partielle et de créer un ordre ambigu

### Résistance aux courses MongoDB

Le réordonnancement a été conçu pour limiter les conflits :
- la route refuse les vues filtrées
- le serveur vérifie que la liste transmise correspond bien à l'ensemble attendu
- si l'ordre a changé entre-temps, PulseBeat renvoie un conflit propre (`409`) au lieu de corrompre la playlist
- en cas d'échec inattendu MongoDB, la route retourne un message propre et journalise l'incident

## Workers persistants d'import YouTube

Les imports de grosses playlists YouTube ne dépendent plus uniquement d'un thread éphémère lié à la requête HTTP. Ils sont maintenant gérés comme de **vrais jobs persistants**.

### Principe

Quand un utilisateur importe une playlist YouTube vers une playlist locale :

1. la playlist locale est créée immédiatement
2. un document de job est enregistré dans la collection `external_import_jobs`
3. le traitement continue en arrière-plan
4. le dashboard `Gérer mon compte` permet de suivre et piloter ce job

### Survie au redémarrage de Flask

Au démarrage de l'application :
- un scheduler léger redémarre automatiquement
- il inspecte les jobs `queued` et les jobs `running` devenus orphelins
- les jobs interrompus sont repris sans intervention utilisateur

Important :
- si l'utilisateur avait demandé une **pause** ou une **annulation** juste avant le redémarrage, cette intention est conservée
- le système n'écrase pas cette demande en re-lançant aveuglément le job

### États possibles

Les jobs d'import peuvent être dans les états suivants :
- `queued`
- `running`
- `paused`
- `completed`
- `failed`
- `canceled`

Ces états sont reflétés à la fois :
- dans la collection `external_import_jobs`
- dans la playlist locale liée (`import_status`, progression, erreur éventuelle)

### Contrôle utilisateur

Depuis `Gérer mon compte`, l'utilisateur voit :
- le nom de la playlist locale
- la source YouTube
- l'état courant
- le nombre de pistes traitées
- le nombre de chansons réellement ajoutées
- un lien direct vers la playlist locale

Actions disponibles :
- `Pause`
- `Reprendre`
- `Annuler`

### Matching intelligent pendant l'import

Pendant l'import :
- PulseBeat tente d'abord de réutiliser une chanson locale publique équivalente
- le matching repose sur une normalisation `titre + artiste`
- si un match local est trouvé, aucune chanson externe doublon n'est créée
- la playlist importée référence alors directement la chanson locale déjà présente sur le serveur

### Résistance aux courses et crashs

Les workers ont été durcis pour rester cohérents :
- réservation atomique d'un job `queued` vers `running`
- heartbeat régulier pour détecter les jobs orphelins
- reprise automatique seulement si le job n'a pas été explicitement mis en pause ou annulé
- `pause` / `resume` / `cancel` utilisent des transitions filtrées côté MongoDB pour éviter les changements d'état incohérents

Si un échec MongoDB ou un crash survient malgré tout :
- PulseBeat tente de remettre le job dans un état cohérent
- si cela échoue, le job passe en `failed` avec un message d'erreur stable
- l'interface doit montrer cet échec au lieu de rester bloquée silencieusement

## Réinitialisation complète de PulseBeat par le root admin

Le `root admin` dispose désormais d'une opération de **réinitialisation complète** de l'instance PulseBeat.

### Ce que fait cette action

La réinitialisation complète :
- efface les données MongoDB de l'application
- supprime les fichiers audio stockés côté serveur
- remet l'instance dans un état proche d'un premier lancement

Cette opération est volontairement extrêmement protégée.

### Séquence de sécurité

1. seul le **root admin** voit l'action dans la zone admin
2. l'admin doit saisir son **mot de passe actuel**
3. PulseBeat envoie ensuite un **courriel de confirmation** dédié
4. après clic sur le lien reçu, une page de confirmation finale s'ouvre
5. un dernier choix `Oui / Non` est demandé avant destruction réelle

Même si la 2FA courriel n'est pas activée sur le compte, cette confirmation par courriel reste obligatoire pour le reset complet.

### Expérience utilisateur

Pendant l'exécution :
- un modal bloquant indique que la réinitialisation est en cours

À la fin :
- un second modal bloquant demande explicitement de **redémarrer le serveur PulseBeat** pour repartir proprement

### Journalisation et sécurité

- l'action est journalisée dans l'audit admin
- le token de reset est consommé une seule fois
- si l'admin annule à la confirmation finale, le processus s'arrête sans effacer les données

## Authentification persistante et option `Se souvenir de moi`

La page de connexion propose désormais une option `Se souvenir de moi`.

Comportement :
- si la case est cochée, la session Flask devient persistante sur une durée plus longue
- si elle n'est pas cochée, le comportement reste celui d'une session plus courte / classique
- l'option est **désactivée par défaut**

Pour aider l'utilisateur à faire un choix éclairé, un point d'aide `?` à côté de la case explique que :
- cela évite de se reconnecter à chaque session
- mais augmente le risque si le cookie de session venait à être volé

Cette option complète le système de sessions liées aux appareils, sans le remplacer.

## Lecteur audio

Le lecteur flottant persiste entre les pages et conserve son état en local.

Comportement notable :
- le lecteur n'apparaît pas du tout tant qu'aucune chanson n'est chargée
- au premier lancement manuel d'une chanson, le lecteur apparaît avec animation puis démarre automatiquement la lecture
- cette auto-lecture initiale reste bloquée sur un 2e onglet PulseBeat si la garde audio multi-onglets est active
- certaines actions du lecteur sont réservées aux comptes connectés :
  - ajout de la chanson courante à une playlist
  - préférences du menu contextuel pour ne plus recommander une chanson ou un artiste
- en lecture de playlist : modes `normal`, `shuffle` et `repeat one` disponibles
- hors playlist : lecture automatique avec recherche de recommandations
- gestion d'erreur de stream côté lecteur avec bannière visible au-dessus des contrôles
- vues disponibles : `mini`, `normale`, `plein écran`
- le bouton de vue affiche le mode suivant, pas le mode actuel
- un libellé d'état indique la vue actuellement active
- bouton `previous` :
  - moins de 5 secondes de lecture : chanson précédente
  - 5 secondes ou plus : redémarrage de la chanson courante
- ce comportement s'applique aussi aux boutons média système compatibles (clavier, écouteurs, contrôles OS)

## Anti-superposition audio multi-onglets

PulseBeat inclut une garde audio pour éviter que plusieurs onglets lisent du son en même temps par erreur.

### Comportement utilisateur

- si un seul onglet PulseBeat est actif : lecture normale
- dès qu'un onglet plus récent est ouvert alors qu'un autre onglet PulseBeat existe déjà :
  - un modal bloquant s'affiche dans l'onglet récent
  - la lecture y est bloquée tant que l'utilisateur ne confirme pas explicitement
  - l'onglet le plus ancien continue à jouer normalement

Options du modal :
- `Garder l'ancien onglet` : ce nouvel onglet reste bloqué pour l'audio
- `Autoriser ici` : l'utilisateur autorise la lecture sur l'onglet récent

### Détails techniques

- registre des onglets actifs dans `localStorage` (`pulsebeat_active_tabs_v1`)
- identifiant tab-level en `sessionStorage` + `runtimeId` pour éviter les collisions lors de duplication d'onglet
- heartbeat périodique toutes les `5s` (`TAB_HEARTBEAT_MS`)
- purge automatique des onglets inactifs après `20s` (`TAB_STALE_MS`)
- désenregistrement propre de l'onglet à la fermeture/navigation (`beforeunload` / `pagehide`)
- réévaluation immédiate via événements `storage` et `visibilitychange`

### Points d'application du blocage

Le garde audio est vérifié :
- au lancement automatique d'une chanson (`autoplay`)
- lors d'une action manuelle play/pause
- lors de la reprise de lecture après changement de page

Si un onglet est bloqué, PulseBeat :
- stoppe la lecture en cours sur cet onglet
- garde l'état du lecteur cohérent
- affiche un message explicite indiquant que l'audio est bloqué tant que l'activation n'est pas confirmée

## PulseBeat Recap

PulseBeat propose maintenant deux formes de recap personnel :

- un **recap annuel automatique**
- un **recap à la demande**

L'objectif est de produire une expérience proche des recaps modernes type Spotify / YouTube Music, mais avec une base de données et un rendu adaptés à PulseBeat.

### Déclencheurs de génération

PulseBeat génère un recap dans trois situations :

1. **recap annuel automatique**
   - il n'est pas envoyé par courriel
   - il apparaît dans la cloche de notifications
   - il est généré de façon paresseuse quand PulseBeat charge réellement les notifications de l'utilisateur
2. **recap annuel à la demande**
   - l'utilisateur choisit une année dans `Gérer mon compte`
   - PulseBeat régénère explicitement ce recap pour cette période
3. **recap personnalisé**
   - l'utilisateur choisit une date de début et une date de fin
   - PulseBeat construit un recap dédié à cette plage

Ce modèle évite de pré-calculer tous les recaps de tout le monde au démarrage, ce qui serait trop coûteux pour une petite instance.

### Construction des données : ordre réel des sources

PulseBeat essaie toujours d'utiliser la source la plus précise disponible pour la période demandée.

Ordre de priorité :

1. **`listening_events`**
2. **fallback `listening_history`**
3. **aucun recap** si aucune des deux sources ne fournit assez de matière

#### Cas 1 : `listening_events` est disponible

PulseBeat utilise la collection `listening_events` si elle trouve de vrais événements `started` dans la période.

Dans ce mode :

- `plays_total` est calculé à partir du nombre d'événements `started`
- `completed_plays` est calculé à partir du nombre d'événements `completed`
- la ventilation mensuelle est calculée à partir des timestamps `created_at`
- les chansons, artistes et genres dominants sont reconstruits à partir des `song_id`
- la durée écoutée est estimée à partir du **plus grand `duration` observé** pour chaque chanson, puis multipliée par le nombre de lectures détectées

C'est le mode le plus fidèle, et c'est celui que PulseBeat étiquette ensuite comme :

- `données précises`

#### Cas 2 : fallback sur `listening_history`

Si PulseBeat ne trouve pas de base événementielle exploitable pour la période, il retombe sur `listening_history`.

Dans ce mode :

- la période est filtrée via `updated_at`, `last_completed_at` ou `created_at`
- `plays_total` est reconstruit à partir de `play_count` avec un minimum de `1`
- `completed_plays` correspond au nombre d'entrées ayant un `last_completed_at`
- les minutes écoutées sont estimées à partir de `last_duration`
- la ventilation mensuelle utilise `updated_at`, sinon `last_completed_at`, sinon `created_at`

Ce mode reste cohérent, mais plus approximatif. Il est affiché dans l'interface comme :

- `estimation intelligente`

#### Cas 3 : aucune donnée suffisante

Si ni `listening_events` ni `listening_history` ne fournissent de matière exploitable :

- aucun recap n'est généré
- PulseBeat renvoie un message utilisateur propre au lieu d'afficher un recap vide

### Pipeline détaillé de calcul

Une fois la période déterminée, PulseBeat exécute ce pipeline :

1. **résolution de la période**
   - année complète pour un recap annuel
   - plage personnalisée inclusive pour un recap manuel
2. **chargement des événements ou de l'historique**
3. **reconstruction des snapshots chansons**
   - titre
   - artiste
   - genre
4. **agrégations principales**
   - nombre total d'écoutes
   - nombre de chansons distinctes
   - nombre d'artistes distincts
   - top chansons
   - top artistes
   - top genres
   - ventilation mensuelle
5. **construction du résumé**
   - top morceau
   - top artiste
   - top genre
   - meilleur mois
6. **persistance MongoDB**
   - le recap complet est stocké dans `user_recaps`

### Réutilisation, régénération et anti-doublons

Chaque recap possède une clé logique `period_key`.

Exemples :

- `annual:2026`
- `custom:2026-01-01:2026-03-31`

PulseBeat s'en sert pour :

- éviter de créer plusieurs recaps pour la même période
- retrouver rapidement un recap déjà calculé
- régénérer explicitement un recap à la demande quand l'utilisateur le demande

Concrètement :

- les recaps automatiques annuels réutilisent l'existant si possible
- les recaps manuels/à la demande peuvent forcer une régénération
- un index unique protège la collection `user_recaps` contre les doublons

### Enrichissement au moment de l'affichage

Le document stocké ne suffit pas à lui seul à produire l'expérience premium finale. Au moment de l'ouverture du recap, PulseBeat enrichit encore les données.

Il ajoute notamment :

- les libellés mensuels localisés (`Mar 2026`, `Apr 2026`, etc.)
- `completion_rate`
- `top_song_share`
- les URLs de détail des chansons
- la vérification d'accessibilité de chaque chanson liée au recap

PulseBeat ne fait pas confiance aveuglément aux anciennes références.

Avant d'exposer une chanson du recap dans l'interface premium, il vérifie :

- que la chanson existe toujours
- que l'utilisateur a encore le droit d'y accéder
- qu'elle est rejouable dans le lecteur actuel

### Comment la bande sonore de fond est choisie

La bande sonore du recap n'est pas une piste arbitraire.

PulseBeat essaie de choisir :

- la première chanson marquante du top recap
- qui est encore accessible
- et qui est réellement rejouable par le moteur audio courant

Si aucune chanson du top ne satisfait ces conditions :

- le recap reste entièrement fonctionnel
- mais sans bande sonore de fond

Si le navigateur refuse l'autoplay :

- l'expérience visuelle continue normalement
- PulseBeat retente au premier geste utilisateur

### Expérience premium plein écran

Le recap “premium” est conçu comme une expérience autonome.

Pendant sa lecture :

- le header PulseBeat est masqué
- le footer est masqué
- le lecteur global est masqué
- la page entière est consacrée au recap

L'utilisateur peut :

- laisser défiler automatiquement les slides
- passer en manuel
- avancer / reculer
- quitter via `X`
- terminer le recap via le bouton final `Terminer`

La dernière slide agit comme une vraie sortie d'expérience :

- export des données
- puis retour simple vers l'accueil

### Slides et contenu affiché

Le recap premium est construit comme une story en plusieurs sections, par exemple :

- introduction générale
- bande sonore du recap
- top morceau
- top artiste
- styles / genres dominants
- timeline mensuelle
- slide finale d'export

Chaque slide peut mixer :

- gros chiffres animés
- cartes de résumé
- barres mensuelles
- top contenus
- bande sonore de fond

### Export des données du recap

La dernière slide propose :

- `JSON`
- `CSV`

Le `JSON` correspond à une représentation structurée exploitable techniquement.

Il contient notamment :

- les métadonnées du recap
- les métriques principales
- les tops
- la ventilation mensuelle
- les enrichissements exposés à l'interface

Le `CSV` fournit une version aplatie plus simple à ouvrir dans un tableur.

### Stockage MongoDB

Les recaps sont stockés dans `user_recaps`.

Clés principales :

- `user_id`
- `period_key`
- `recap_type`
- `year`
- `period_start`
- `period_end`
- `basis`
- `metrics`
- `top_songs`
- `top_artists`
- `top_genres`
- `monthly_breakdown`
- `summary`
- `updated_at`

### Optimisation et stratégie serveur

Le système de recap est volontairement :

- **paresseux** pour l'annuel automatique
- **persisté** après calcul
- **rejouable** sans recalcul tant que la période n'est pas régénérée
- **adaptatif** selon la qualité des données disponibles

Cela réduit :

- les scans inutiles sur MongoDB Atlas
- les recalculs répétés
- la latence lors des ouvertures suivantes
- la pression côté serveur pour les utilisateurs qui n'ouvrent jamais leur recap

## Gestures tactiles et navigation mobile

PulseBeat ajoute maintenant plusieurs gestures mobiles pour fluidifier l'interface sans multiplier les boutons.

### Philosophie générale

PulseBeat n'active pas des gestes au hasard sur toute l'interface.

Chaque geste est limité à une surface précise et à une direction dominante, pour éviter les conflits avec :

- la barre de progression audio
- les boutons d'action
- le scroll vertical naturel
- les tap/clicks classiques

Dans la plupart des cas, PulseBeat exige :

- un déplacement suffisamment net
- et une dominance claire de l'axe horizontal ou vertical

Cela évite que de petits tremblements de doigt déclenchent une mauvaise action.

### Lecteur mobile : mini ↔ plein écran

Sur mobile, PulseBeat n'expose que deux modes de lecteur :

- `mini`
- `plein écran`

Le passage par geste fonctionne comme ceci :

- swipe **vers le haut** depuis le mini lecteur : ouverture en plein écran
- swipe **vers le bas** depuis le plein écran : repli vers le mini lecteur

Important :

- le geste n'est accepté que depuis la poignée du lecteur ou la zone méta chanson
- les contrôles sensibles comme la timeline ne servent pas de zone de geste
- cela évite les conflits avec le seek audio

### Menu hamburger mobile

Le menu mobile suit maintenant une logique plus proche d'une vraie app tactile :

- ouverture par swipe depuis le bord gauche
- animation visuelle en **slide in gauche → droite**
- fermeture par swipe inverse **droite → gauche**
- fermeture aussi possible par :
  - tap sur le backdrop
  - clic/tap sur un lien du menu
  - touche `Escape`

Le mouvement visuel du menu a été aligné sur le geste lui-même :

- on ouvre depuis la gauche, le panneau vient de la gauche
- on ferme en ramenant vers la gauche, le panneau repart vers la gauche

Cela rend l'interaction beaucoup plus intuitive pour la main.

### Panneau de notifications

Sur mobile, le panneau de notifications peut être fermé d'un geste simple :

- swipe **vers le bas** sur le panneau

Ce geste est utile parce que le panneau s'affiche comme une surface flottante au-dessus de l'interface, souvent près du menu mobile.

### Recap premium

Le recap possède aussi ses propres gestes :

- swipe gauche : slide suivante
- swipe droite : slide précédente
- swipe descendant depuis la zone haute du recap : fermeture rapide

Le recap combine aussi plusieurs formes de navigation :

- défilement automatique
- boutons visuels
- clavier desktop (`flèche gauche`, `flèche droite`, `Escape`)
- bouton `X`
- bouton final `Terminer`

### Pourquoi PulseBeat limite volontairement le nombre de gestes

L'objectif n'est pas de transformer toute l'interface en surface à gestures, mais d'ajouter les gestes uniquement là où ils apportent un vrai gain :

- ouverture/fermeture d'une grande surface
- changement de mode du lecteur
- navigation dans une expérience plein écran
- fermeture rapide d'un panneau mobile

Cette approche garde l'interface :

- plus prévisible
- plus facile à apprendre
- plus sûre pour les contrôles audio

### Moteur hybride local + YouTube

Le lecteur sélectionne automatiquement le moteur de lecture selon la chanson :

- source locale (`upload`) : élément `<audio>`
- source YouTube : IFrame API YouTube (player caché côté DOM)

Contrôles unifiés sur les deux moteurs :
- play/pause/next/previous
- seek
- vitesse (`x1`, `x1.25`, `x1.5`)
- mise à jour du titre d'onglet
- envoi de progression d'écoute

### Gestion d'indisponibilité YouTube

Quand une lecture YouTube échoue :

- le lecteur effectue un retry automatique unique sur erreurs transitoires
- il évite les sauts en cascade (`next`) via un verrou court anti-burst
- seul le cas `404` YouTube (code vidéo introuvable) marque la chanson comme indisponible globalement
- les chansons indisponibles sont grisées dans les listes et auto-skippées en lecture automatique
- si l'utilisateur lance manuellement une chanson marquée indisponible et qu'elle fonctionne, elle est réactivée automatiquement

### Bouton Lecture dans les recommandations

Le bouton `Lecture` cherche désormais la meilleure file dans cet ordre :

1. `PAGE_SONG_OBJECTS` (liste principale)
2. `PAGE_RECOMMENDED_SONGS` (recommandations)
3. fallback sur une file contenant uniquement la chanson cliquée

Cela évite les mauvais index de lecture dans les blocs de recommandations (accueil et page détail).

### Déduplication de la file et recommandations automatiques

PulseBeat empêche désormais les doublons dans une même file d'attente :

- au moment où une file est créée depuis une page (`PAGE_SONG_OBJECTS`, recommandations, playlist)
- au moment où l'état du lecteur est restauré depuis le stockage local
- avant d'ajouter une recommandation automatique en fin de file

La déduplication est faite par `song.id`.

Effet pratique :
- une même chanson ne peut pas apparaître deux fois dans la même file automatique
- les restaurations de session nettoient aussi les doublons anciens si nécessaire

### Sous-titres en plein écran (cas par cas)

Le lecteur charge les sous-titres via `GET /songs/<song_id>/lyrics` à chaque changement de chanson.

Cas par cas :

1. Vue du lecteur `mini` ou `normale`
- Le panneau de sous-titres est caché.
- Aucun rendu de lignes de lyrics n'est affiché dans ces modes.

2. Vue `plein écran` + chanson sans sous-titres
- Le panneau s'affiche.
- Le message "Aucun sous-titre disponible" est affiché.

3. Vue `plein écran` + sous-titres synchronisables (`lyrics_auto_sync=true` + cues)
- Le lecteur affiche un mode synchronisé.
- La ligne active est déterminée selon le timestamp courant.
- 3 lignes sont rendues autour de la position courante : ligne précédente, ligne active, ligne suivante.
- La ligne active est visuellement mise en évidence.
- Le rendu est recalculé pendant la lecture et après un seek.

4. Vue `plein écran` + sous-titres non synchronisés (pas de cues exploitables)
- Le lecteur affiche le texte complet des paroles dans un bloc `pre`.
- Aucun suivi ligne-par-ligne par timestamp n'est appliqué.

5. Changement de chanson pendant la lecture
- L'état lyrics est réinitialisé, puis rechargé pour la nouvelle chanson.
- Si la requête lyrics échoue, le lecteur retombe proprement sur l'affichage "pas de sous-titres".

6. Données prises en compte côté lecteur
- `lyrics_text` : texte brut des sous-titres.
- `lyrics_auto_sync` : indique si le mode synchronisé doit être tenté.
- `lyrics_cues` : timestamps + texte utilisés pour le rendu synchronisé.

## Profils publics

Chaque utilisateur possède une page publique accessible via `/users/<username>`.

Contenu visible :
- informations publiques du compte
- chansons visibles selon les permissions réelles
- playlists visibles selon les permissions réelles
- activité publique pertinente

Des liens vers ces profils sont disponibles :
- depuis la page de détail d'une chanson pour voir le profil de l'uploadeur
- depuis les commentaires et réponses
- depuis `Gérer mon compte` pour ouvrir sa propre page publique

## Validations et JavaScript

PulseBeat applique deux niveaux de validation :
- validation JavaScript en direct pour un retour immédiat sur les formulaires
- validation serveur systématique pour empêcher tout contournement côté client

Les validations en direct couvrent notamment :
- format d'e-mail
- politique de mot de passe
- confirmation de mot de passe
- unicité du nom d'utilisateur et de l'e-mail
- champs requis dans les formulaires principaux
- contraintes spécifiques comme les utilisateurs requis pour certaines ressources privées

Si JavaScript est désactivé :
- un écran bloquant s'affiche sur toutes les routes utilisant le layout principal
- l'application reste volontairement inutilisable tant que JavaScript n'est pas réactivé

### Code client obfusqué

Les sources JavaScript restent volontairement simples à modifier dans le dépôt :

- `static/js/app.js`
- `static/js/player.js`
- `static/js/admin.js`

Pour le navigateur, PulseBeat peut servir à la place des bundles obfusqués générés dans :

- `static/dist/app.obf.js`
- `static/dist/player.obf.js`
- `static/dist/admin.obf.js`

Objectif :
- garder un workflow de développement confortable côté projet
- éviter d'exposer les sources lisibles directement au public

## Modération automatique

- Les créations/modifications de chansons et playlists, ainsi que les commentaires, sont bloqués si des termes vulgaires connus sont détectés.
- L'utilisateur reçoit un avertissement avec le nombre restant avant bannissement automatique.
- Chaque détection incrémente un compteur d'infractions.
- Au 3e strike, le compte est banni automatiquement (durée indéfinie) jusqu'à débannissement manuel par un admin.
- Une alerte est ajoutée au dashboard admin et une notification admin peut être envoyée par e-mail.

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
- PyOTP (2FA par application d'authentification)
- JavaScript vanilla
- HTML / CSS

## Structure du projet

- `app.py` : création de l'application Flask, config, startup
- `extensions.py` : connexion MongoDB et collections
- `auth_helpers.py` : helpers auth, sécurité, mail, permissions
- `server_cache.py` : cache serveur intelligent (JSON public + audio YouTube local)
- `blueprints/accounts.py` : auth, setup initial, reset password, vérification e-mail, Google OAuth, profils publics, 2FA multi-méthodes, import YouTube persistant
- `blueprints/main.py` : accueil et navigation principale
- `blueprints/songs.py` : chansons, détails, votes, commentaires, signalements
- `blueprints/playlists.py` : playlists, collaborateurs, recherche, partage, réordonnancement persistant
- `blueprints/admin.py` : dashboard admin, réinitialisation complète de la plateforme
- `templates/` : vues Jinja
- `templates/accounts/public_profile.jinja` : page publique utilisateur
- `static/js/player.js` : lecteur audio flottant
- `static/js/app.js` : interactions UI et validations côté client
- `static/js/admin.js` : interactions UI de la zone admin
- `scripts/build-client-js.mjs` : build des bundles JavaScript obfusqués
- `static/dist/` : bundles JavaScript servis au client quand l'obfuscation est activée
- `package.json` : dépendances/scripts Node du pipeline JavaScript client
- `static/css/styles.css` : styles

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
npm install
copy .env.example .env
npm run build:client-js
python app.py
```

Puis ouvrir `http://127.0.0.1:5000`.

Workflow recommandé après modification d'un fichier dans `static/js/` :

```bash
npm run build:client-js
```

Cela régénère les bundles obfusqués servis au navigateur.


## Recommandation d'hébergement

En raison de la complexité actuelle de PulseBeat (lecteur persistant, modération, recherche/suggestions, e-mails transactionnels, workflows de sous-titres, zone admin), les hébergeurs low-end ne sont pas recommandés.

Recommandé :
- self-hosting (VPS/serveur dédié) avec ressources stables
- ou un hébergeur payant de niveau production

Non recommandé :
- offres gratuites/ultra low-end avec CPU/RAM limités, sleep forcé ou quotas réseau très stricts

## Mises à jour récentes

- Dashboard admin : les alertes sécurité/modération en haut de page peuvent être fermées individuellement (`X`) sans impacter les autres admins.
- Un toast de confirmation apparaît 10 secondes avec bouton `Annuler` pour restaurer immédiatement l'alerte.
- Correction du lecteur pour garantir le bon fonctionnement de `previous` et `next` (UI + contrôles média système).
- Le lecteur est maintenant masqué tant qu'aucune chanson n'est chargée, puis apparaît avec animation au premier lancement.
- Le premier lancement manuel d'une chanson démarre automatiquement la lecture sur l'onglet principal.
- Les recommandations et restaurations de file empêchent désormais les doublons de chansons dans une même file.
- Les recaps PulseBeat annuels et personnalisés sont maintenant disponibles, avec notification automatique et export JSON/CSV.
- Le menu mobile, les notifications et le lecteur plein écran gagnent des gestures tactiles plus naturelles.
- Les bundles JavaScript obfusqués peuvent maintenant être servis au navigateur tout en gardant les sources projet éditables.


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
- `external_integrations`
- `external_playlists`
- `external_import_jobs`
- `data_exports`
- `song_votes`
- `song_comments`
- `listening_history`
- `listening_events`
- `user_recaps`
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

### Réinitialisation complète de la plateforme (optionnel, root admin)

Variables disponibles :
- `PLATFORM_RESET_TOKEN_MAX_AGE=1800` (durée de validité du lien envoyé au root admin pour confirmer le reset complet)
- `PLATFORM_RESET_SALT=pulsebeat-platform-reset` (salt du token de confirmation du reset complet)

Comportement :
- seul le root admin peut initier cette action
- l'opération exige mot de passe + courriel de confirmation
- le lien n'est utilisable qu'une fois

### 2FA (optionnel, recommandé)

Variables disponibles :
- `TWO_FACTOR_CODE_MAX_AGE=600` (durée de validité du code 2FA par courriel, en secondes)
- `TWO_FACTOR_TOGGLE_TOKEN_MAX_AGE=3600` (durée de validité du lien de confirmation activation/désactivation de la méthode courriel)
- `TWO_FACTOR_TOGGLE_SALT=pulsebeat-two-factor-toggle` (salt du token de confirmation 2FA courriel)
- `TWO_FACTOR_TOTP_PENDING_MAX_AGE=900` (durée de vie du secret TOTP en attente de confirmation pendant le setup)

### Sessions liées aux appareils et connexions persistantes (optionnel, recommandé)

Variables disponibles :
- `DEVICE_COOKIE_NAME=pulsebeat_device_id` (nom du cookie d'appareil PulseBeat)
- `DEVICE_COOKIE_MAX_AGE=31536000` (durée de vie du cookie d'appareil, en secondes)
- `DEVICE_APPROVAL_TOKEN_MAX_AGE=1800` (durée de validité du lien d'approbation d'un nouvel appareil)
- `DEVICE_APPROVAL_SALT=pulsebeat-device-approval` (salt du token d'approbation d'appareil)
- `REMEMBER_ME_SESSION_DAYS=30` (durée des sessions persistantes quand `Se souvenir de moi` est coché)

### JavaScript client (optionnel)

Variables disponibles :
- `JS_SERVE_OBFUSCATED=1` (sert les bundles obfusqués du dossier `static/dist/` si disponibles)

Comportement :
- si la variable vaut `1` et que les bundles existent, PulseBeat sert `static/dist/*.obf.js`
- sinon, PulseBeat retombe automatiquement sur les sources lisibles de `static/js/`
- cela permet de garder un workflow simple en développement tout en réduisant l'exposition des sources côté navigateur

### Cache serveur intelligent (optionnel, recommandé)

Variables disponibles :
- `SERVER_CACHE_DIR=` (racine locale du cache serveur ; vide = `instance/server_cache`)
- `SERVER_CACHE_JSON_MAX_BYTES=20971520` (taille max du cache JSON)
- `SERVER_CACHE_JSON_MAX_FILES=500` (nombre max de fichiers JSON)
- `PUBLIC_PROFILE_CACHE_TTL_SECONDS=180` (TTL des profils publics cacheables)
- `PUBLIC_PLAYLIST_CACHE_TTL_SECONDS=180` (TTL des playlists publiques cacheables)
- `POPULAR_PUBLIC_SONGS_CACHE_TTL_SECONDS=180` (TTL des agrégats de popularité utilisés dans les recommandations)
- `YOUTUBE_AUDIO_CACHE_ENABLED=1` (active le cache audio local des chansons YouTube)
- `YOUTUBE_AUDIO_CACHE_MAX_BYTES=536870912` (taille max du cache audio YouTube local)
- `YOUTUBE_AUDIO_CACHE_MAX_FILES=80` (nombre max de fichiers audio YouTube gardés en cache)

Comportement :
- les fichiers audio YouTube récemment écoutés peuvent être conservés localement sur le serveur
- les fichiers les moins récemment utilisés sont supprimés en premier quand les limites sont dépassées
- les données publiques coûteuses sont sérialisées en JSON côté serveur avec invalidation ciblée + TTL court

### Sync bibliothèque YouTube (optionnel)

Pour activer la connexion de bibliothèques externes depuis `Gérer mon compte` :

- `YOUTUBE_SYNC_CLIENT_ID=...`
- `YOUTUBE_SYNC_CLIENT_SECRET=...`

Sans ces variables, les boutons d'intégration restent visibles mais marqués `Non configuré`.

État actuel de la fonctionnalité :

- la synchronisation YouTube fonctionne bien (connexion OAuth, récupération des playlists, import dans PulseBeat)
- la lecture des chansons importées depuis YouTube fonctionne pour certaines pistes uniquement
- les pistes YouTube réellement écoutées peuvent maintenant être mises en cache audio localement sur le serveur pour accélérer les écoutes suivantes
- selon les titres, la lecture peut échouer à cause de restrictions côté YouTube/Google API (droits, disponibilité, limitations d'accès/embeds), ou de limites techniques côté PulseBeat sur les sources externes

Détails techniques de l'import :

- synchronisation OAuth vers les collections :
  - `external_integrations` (tokens)
  - `external_playlists` (playlists + tracks externes)
  - `external_import_jobs` (jobs persistants d'import local)
- import en playlist locale non bloquant :
  - la création démarre immédiatement
  - le traitement est délégué à un worker persistant en arrière-plan
  - l'utilisateur peut suivre les jobs dans `Gérer mon compte`
  - chaque job peut être mis en pause, repris ou annulé
- reprise après redémarrage :
  - les jobs `queued` reprennent automatiquement
  - les jobs `running` interrompus sont relancés par le scheduler
  - les demandes `pause` / `cancel` déjà enregistrées sont respectées au redémarrage
- états exposés côté interface :
  - `pending`, `running`, `paused`, `completed`, `failed`, `canceled`
- réutilisation intelligente des chansons locales publiques :
  - avant de créer une chanson externe, l'import cherche une chanson locale `upload` + `public`
  - matching par normalisation `titre + artiste` (sans accents, ponctuation neutralisée)
  - si match trouvé, aucune chanson externe n'est créée et la chanson locale est ajoutée à la playlist importée
  - si aucun match, l'entrée externe est créée normalement

## Premier lancement

Si aucun admin principal n'existe dans la base, l'application bloque l'accès normal et affiche le setup initial.

Le compte admin principal créé lors de ce setup :
- devient `root admin`
- ne peut pas être supprimé
- doit lui aussi vérifier son e-mail avant la première connexion

Au démarrage, l'application tente aussi de créer des index uniques sur :
- `users.email_normalized`
- `users.username_normalized`
- `listening_history(user_id, song_id)`
- `song_votes(song_id, user_id)`
- `comment_votes(comment_id, user_id)` (si la collection est active)
- `creator_subscriptions(creator_id, subscriber_id)`
- `user_notifications(recipient_user_id, notification_type, content_type, content_id)`

Pour les collections à risque de concurrence (`listening_history`, votes), PulseBeat tente automatiquement une déduplication avant la création des index uniques.

Si une création d'index échoue malgré tout, l'application continue de démarrer et écrit un warning en logs (sans crash).

## Développement

Vérifier la syntaxe Python :

```bash
python -m py_compile app.py auth_helpers.py blueprints\accounts.py blueprints\admin.py blueprints\main.py blueprints\songs.py blueprints\playlists.py i18n.py
```

Construire les bundles JavaScript obfusqués :

```bash
npm run build:client-js
```

## Fiabilité API

- Le endpoint `POST /songs/<id>/progress` est durci avec mise à jour MongoDB sécurisée + retries pour réduire les conflits de concurrence.
- Les endpoints critiques de mutation utilisent désormais des écritures Mongo sécurisées :
  - progression d'écoute
  - votes chansons
  - votes commentaires
  - disponibilité des chansons externes
- Les flux sensibles de sécurité session/appareil ont été renforcés :
  - mise à jour ou insertion idempotente des `trusted_devices`
  - enregistrement de `active_sessions` par appareil sans doublons logiques
  - approbation de nouveaux appareils avec mise à jour ciblée de `pending_device_approvals`
- La gestion de compte limite mieux les courses MongoDB :
  - changement de `username` avec rattrapage propre des collisions d'index uniques
  - rotation de `session_token_version` via écriture Mongo sécurisée
  - reconnexion post-changement de mot de passe protégée par gestion d'erreur locale avant fallback global
- Les abonnements créateurs sont durcis :
  - abonnement via `upsert` atomique
  - désabonnement idempotent
  - notifications de publication protégées contre les doublons par index uniques
- Les profils publics et le retour après abonnement/désabonnement ont été optimisés :
  - filtrage des chansons et playlists visibles directement côté MongoDB
  - projections de champs allégées sur les pages publiques
  - index dédiés pour accélérer le chargement des profils créateurs, playlists et commentaires associés
- Un handler global `PyMongoError` renvoie une réponse propre `503` (JSON pour API/AJAX, page erreur pour HTML) au lieu de faire planter l'application.
- Les index uniques sur historique/votes limitent fortement les doublons créés par accès concurrents.
- Quand PulseBeat peut récupérer localement une course MongoDB, il le fait et renvoie un message utilisateur propre ; la page d'erreur n'est utilisée qu'en dernier recours.
- Le favicon est servi en `204` via `/favicon.ico` pour éviter les 404 répétitifs en logs
- Correction d'un cas de persistance d'état UI qui pouvait bloquer `previous/next` dans le lecteur (boutons page + boutons média système)

## Intégrité automatique des documents MongoDB et erreur 422

PulseBeat inclut maintenant un watchdog d'intégrité côté serveur pour éviter qu'un document corrompu ou partiellement invalide fasse tomber l'application entière.

L'objectif est double :

- protéger l'expérience utilisateur en continuant l'opération quand c'est raisonnablement possible
- empêcher qu'une donnée cassée ne provoque des `500` en cascade sur plusieurs pages

### Philosophie générale

PulseBeat **ne supprime pas immédiatement** un document invalide.

La stratégie est volontairement progressive et **non destructive par défaut** :

1. **validation structurelle minimale**
2. **tentative de récupération locale et persistée**
3. **si la lecture n'est pas fatale, conservation du document tant que l'opération continue**
4. **suppression seulement en dernier recours sur un chemin fatal**
5. **erreur HTTP `422` si l'opération ne peut pas continuer proprement**

Autrement dit :

- si la donnée peut être réparée sans ambiguïté, PulseBeat la répare
- si la donnée peut être ignorée sans casser la page, PulseBeat l'ignore ou la laisse passer telle quelle
- si la donnée reste inutilisable et casse une opération centrale, PulseBeat la supprime alors seulement et bloque l'opération concernée

### Plus de purge préventive au démarrage

Le watchdog ne fait plus de nettoyage destructif au démarrage de l'application.

En particulier :

- les routines de bootstrap, d'indexation ou de déduplication ne déclenchent plus de suppression automatique simplement parce qu'un document projeté ou partiel ne contient pas tous les champs métier habituels
- les documents MongoDB partiels récupérés via projection ne sont plus traités comme "corrompus" uniquement parce qu'un champ non projeté n'est pas présent dans l'objet Python

Cela évite les faux positifs du type `missing user_id` sur des lectures partielles pourtant normales.

### Ce que PulseBeat considère comme récupérable

Le watchdog ne tente pas de "deviner" des données métier complexes. Il ne répare que les cas simples et sûrs.

Exemples de récupération automatique :

- **utilisateurs**
  - conversion des champs de sécurité attendus en listes vides si leur format est cassé :
    - `trusted_devices`
    - `active_sessions`
    - `dismissed_admin_alerts`
    - `pending_device_approvals`
- **chansons**
  - remplacement d'un `title` invalide par `Untitled`
  - remplacement d'un `artist` invalide par `Unknown artist`
  - remise à vide de champs texte secondaires invalides :
    - `genre`
    - `source_type`
    - `source_url`
    - `external_provider`
    - `availability_reason`
  - remise à `[]` de `shared_with` si le champ est corrompu
  - normalisation ou fallback de `visibility` vers `public`
- **playlists**
  - remplacement d'un nom vide/invalide par `Playlist`
  - remise à `[]` de `song_ids` ou `collaborator_ids` si le format est corrompu
  - normalisation ou fallback de `visibility` vers `private`
- **commentaires**
  - conversion d'un contenu scalaire en texte
  - fallback vers un texte neutre si le contenu n'est plus exploitable
- **historique d'écoute**
  - normalisation de `play_count` en entier
  - remise à plat de `last_position` / `last_duration` en flottants sûrs
- **votes chansons / commentaires**
  - coercition prudente du `vote` vers `1` ou `-1` quand la valeur reste interprétable
- **signalements**
  - normalisation de `target_type`
  - fallback du `status` vers `open`
  - conversion du motif en texte si besoin
- **audit admin**
  - fallback sur `action` / `target_type` si un champ texte critique a été cassé
  - encapsulation des `details` en objet si leur type est invalide
- **abonnements créateurs**
  - normalisation de `notifications_enabled` en booléen
- **notifications internes**
  - normalisation de `notification_type`, `content_type`, `content_title`, `is_read`
- **workers et intégrations externes**
  - récupération prudente des statuts et champs texte des documents :
    - `external_integrations`
    - `external_playlists`
    - `external_import_jobs`
    - `data_exports`
- **leaderboard Dino 418**
  - normalisation de `best_score`, `is_robot`, `actor_type`, `display_name`, `guest_code`

Quand cette récupération réussit :

- PulseBeat essaie de persister immédiatement les champs réparés en base
- la requête continue sans afficher de page d'erreur
- un warning est journalisé côté serveur pour garder une trace technique

### Quand PulseBeat ignore simplement l'élément

Sur certaines vues liste, un document cassé n'a pas besoin de faire échouer toute la page.

Exemples :

- listes de chansons sur l'accueil
- recommandations
- historique d'écoute
- chansons d'une playlist
- éléments secondaires d'un profil public
- listes utilisateurs/commentaires/chansons en zone admin
- notifications internes
- abonnements créateurs
- workers d'import YouTube et playlists externes
- leaderboard du `/dino`

Dans ces cas :

- PulseBeat tente d'abord la récupération
- si la récupération échoue, l'élément est retiré du rendu ou laissé intact tant qu'il ne casse pas la suite
- le reste de la page continue normalement

### Suppression en dernier recours

Si le document est toujours invalide après tentative de récupération, PulseBeat ne le supprime plus immédiatement.

La suppression automatique devient le **dernier recours**, uniquement quand la donnée casse réellement une opération centrale.

Elle est utilisée surtout quand :

- le document n'a plus de structure de base fiable
- le document principal d'une opération reste inutilisable après normalisation
- laisser le document en place risquerait de reproduire la même panne à chaque requête
- la requête a atteint un chemin fatal où PulseBeat ne peut plus continuer proprement avec ce document

Quand une suppression automatique a lieu :

- PulseBeat supprime le document dans la collection concernée
- enregistre une entrée d'audit admin
- met à jour `system_status` avec la clé `invalid_document_watchdog`
- informe tous les admins du problème et de la collection touchée
- journalise aussi l'événement côté serveur

### Quand PulseBeat renvoie une erreur 422

Si le document corrompu est **central** à l'opération en cours, qu'il n'a pas pu être réparé proprement et qu'il casse la logique attendue, PulseBeat refuse de continuer et renvoie une erreur HTTP `422`.

Concrètement, cela couvre les cas où :

- la page ou l'action dépend directement de ce document pour fonctionner
- l'ignorer produirait un résultat incohérent ou dangereux
- la suppression seule ne permet pas de terminer la requête proprement

Comportement :

- pour HTML : page d'erreur personnalisée `422`
- pour AJAX / API JSON : réponse JSON propre avec message utilisateur

Le but est d'expliquer qu'il s'agit d'une donnée invalide, pas d'une panne MongoDB générale ni d'un crash interne opaque.

### Collections et points d'entrée actuellement protégés

Le watchdog couvre déjà les flux les plus sensibles et fréquents :

- récupération de l'utilisateur courant et wrappers `login_required` / `admin_required`
- sérialisation des chansons
- vues de l'accueil et recommandations
- détails chansons
- profils publics
- widgets `Gérer mon compte` liés aux intégrations externes et workers persistants
- détails playlists et listes de chansons associées
- historique d'écoute
- votes chansons / votes commentaires
- commentaires et fragments de commentaires
- signalements
- abonnements créateurs et notifications internes
- leaderboard global du Dino `418`
- plusieurs listes de la zone admin (`users`, `songs`, `comments`, `reports`, `audit logs`)
- documents d'état et de configuration transverses (`system_status`, `app_settings`)
- navigation globale chargée sur presque toutes les pages (ex. playlists du header)
- certaines routines internes de maintenance/dédoublonnage qui passent sur des lots de documents

Cela permet de protéger les écrans les plus visibles sans attendre qu'une corruption se propage partout.

Collections désormais prises en charge par le watchdog :

- `users`
- `songs`
- `playlists`
- `song_comments`
- `song_votes`
- `comment_votes`
- `listening_history`
- `song_reports`
- `admin_audit`
- `creator_subscriptions`
- `user_notifications`
- `external_integrations`
- `external_playlists`
- `external_import_jobs`
- `data_exports`
- `system_status`
- `app_settings`
- `dino_leaderboard`

### Relation avec les autres handlers d'erreur

Ce mécanisme complète les autres défenses existantes :

- `PyMongoError` global continue de renvoyer une erreur `503` propre quand MongoDB lui-même échoue
- le watchdog documents invalides traite un problème différent : **une donnée stockée, mais mal formée**
- PulseBeat essaie donc :
  - d'abord de récupérer la donnée
  - ensuite de l'ignorer si c'est sans danger
  - puis seulement de supprimer / renvoyer `422`

En résumé :

- `503` = problème d'accès ou d'écriture MongoDB
- `422` = donnée présente, mais invalide ou corrompue pour l'opération demandée

## Gestion du stockage saturé et erreur 507

PulseBeat inclut maintenant une protection dédiée contre les situations où le stockage n'est plus suffisant pour continuer à fonctionner proprement.

Le but n'est pas seulement d'afficher une erreur, mais surtout d'éviter qu'une instance continue à écrire dans un environnement déjà saturé, ce qui pourrait provoquer :

- des uploads incomplets
- des reconstructions audio cassées
- des écritures MongoDB partielles ou refusées
- des comportements incohérents selon la route appelée

### Quand PulseBeat déclenche un 507

PulseBeat peut déclencher une erreur HTTP `507 Insufficient Storage` dans deux grandes familles de cas :

- le **serveur web** n'a plus assez d'espace libre local
- la **base MongoDB** remonte un signal crédible indiquant un quota ou un stockage saturé

Concrètement, PulseBeat surveille :

- l'espace libre du serveur local sur les chemins critiques :
  - dossier `instance`
  - dossier d'uploads audio
  - dossier de cache serveur
- les erreurs MongoDB contenant des indices de quota plein / stockage plein / espace insuffisant
- au setup, un contrôle best effort de l'état de stockage MongoDB via `dbStats` quand cette information est disponible

### Comportement côté serveur web

Pour le stockage local, PulseBeat effectue une vérification proactive avant les requêtes importantes.

Si l'espace libre descend sous le seuil minimal configuré :

- PulseBeat marque l'instance comme `storage full`
- la réponse courante devient une erreur `507`
- toutes les requêtes suivantes restent bloquées jusqu'au redémarrage du serveur

Cette vérification sert surtout à éviter qu'une instance continue à accepter :

- de nouveaux fichiers audio
- des reconstructions de cache
- des opérations de maintenance disque

alors que le disque est déjà trop proche de la saturation.

### Comportement côté MongoDB

Pour MongoDB, PulseBeat utilise une stratégie hybride :

- **proactive** au setup quand `dbStats` fournit assez d'information
- **réactive** pendant l'exécution normale quand MongoDB renvoie une erreur compatible avec un quota plein ou un stockage saturé

Cette distinction est importante parce que, selon l'hébergeur ou le plan utilisé (par exemple certains contextes MongoDB Atlas), les métriques de capacité ne sont pas toujours suffisamment détaillées pour faire un pré-contrôle parfait.

Donc :

- si PulseBeat peut estimer proprement l'espace libre MongoDB, il l'utilise
- sinon, il laisse l'application démarrer
- mais au premier vrai signal de stockage saturé renvoyé par MongoDB, il bascule immédiatement en mode `507`

### Verrouillage global jusqu'au redémarrage

Une fois qu'un `507` a été détecté, PulseBeat **verrouille toute la plateforme jusqu'au prochain redémarrage du serveur**.

Ce verrou est volontairement conservateur.

Il évite le scénario où :

- une première route échoue pour stockage plein
- une deuxième route semble encore marcher
- puis une troisième casse plus gravement parce que l'instance continue malgré un état déjà dangereux

Quand ce verrou est actif :

- les routes applicatives sont bloquées
- PulseBeat renvoie `507` au lieu de continuer à traiter normalement
- le verrou ne se retire pas tout seul pendant l'exécution
- il faut libérer de l'espace **puis redémarrer le serveur**

L'idée est de forcer un retour à un état propre plutôt que d'essayer de “survivre à moitié” dans une instance déjà dégradée.

### Effet sur le setup initial

Le setup admin initial n'est pas exempté.

Si PulseBeat détecte qu'il n'y a pas assez d'espace disponible pendant cette phase :

- le setup est bloqué
- aucun compte root admin ne doit être créé dans un environnement déjà saturé
- l'utilisateur doit d'abord libérer de l'espace
- puis redémarrer l'application

Cela évite de faire démarrer une plateforme neuve sur une base déjà instable.

### Rendu de la page 507

La page `507` est traitée comme un véritable écran de blocage.

Contrairement aux autres pages d'erreur :

- le header n'est plus affiché
- le footer / lien de licence n'est plus affiché
- le lecteur de musique n'est plus rendu
- `player.js` n'est pas chargé
- les raccourcis `Accueil` et `Connexion` de la page d'erreur ne sont pas affichés

Autrement dit, pour `507`, PulseBeat ne laisse visible que le contenu principal de la page d'erreur.

Le but est d'éviter toute confusion : ce n'est pas une erreur “navigable”, c'est un état de blocage global de l'instance.

### Différence entre 507, 503, 422 et 409

Ces codes ont maintenant des rôles distincts :

- `507` = manque d'espace ou quota saturé côté serveur web, MongoDB, ou les deux
- `503` = panne temporaire de service ou erreur d'accès MongoDB sans signal clair de stockage saturé
- `422` = donnée présente mais invalide/corrompue pour l'opération demandée
- `409` = conflit logique entre la requête et l'état actuel des données

Exemple :

- playlist modifiée entre deux actions concurrentes : `409`
- document principal invalide malgré tentative de récupération : `422`
- MongoDB indisponible ou timeout sans preuve de quota plein : `503`
- disque serveur plein ou quota MongoDB dépassé : `507`

### Variables d'environnement associées

PulseBeat expose plusieurs variables pour régler le seuil de protection :

- `SERVER_STORAGE_MIN_FREE_BYTES`
  - espace libre minimal exigé côté serveur web
- `DATABASE_STORAGE_MIN_FREE_BYTES`
  - espace libre minimal exigé côté base quand cette information peut être estimée proprement
- `DATABASE_STORAGE_CAPACITY_BYTES`
  - capacité totale forcée côté base si l'hébergeur ne fournit pas une métrique exploitable via `dbStats`

En pratique :

- si tu veux une protection simple, règle surtout `SERVER_STORAGE_MIN_FREE_BYTES`
- si tu héberges MongoDB toi-même ou si tu connais la capacité réelle de ton cluster, `DATABASE_STORAGE_CAPACITY_BYTES` peut rendre le contrôle MongoDB plus fiable
- si ton fournisseur MongoDB n'expose pas assez d'information, PulseBeat reste protégé grâce au fallback réactif sur les vraies erreurs MongoDB

### Philosophie de conception

Le `507` dans PulseBeat est volontairement strict.

Le projet préfère :

- bloquer franchement l'instance
- demander un redémarrage après nettoyage

plutôt que :

- continuer à moitié
- perdre des fichiers
- ou laisser des opérations critiques réussir une fois sur deux selon la route appelée

Cette approche est particulièrement utile avec :

- des serveurs modestes
- des caches audio locaux
- des uploads utilisateur
- des clusters MongoDB à quota limité comme certains plans gratuits Atlas

## Gestion des erreurs 503, 408 et 429

PulseBeat gère maintenant séparément les problèmes de surcharge, de latence excessive et de comportement automatisé trop agressif.

L'objectif est double :

- garder l'instance en vie aussi longtemps que possible sans la laisser s'effondrer silencieusement
- protéger la plateforme contre les rafales de requêtes non humaines ou les connexions franchement instables

### Erreur 503 : serveur fatigué, mode limp et mode latched

Quand PulseBeat estime qu'il est en surcharge ou qu'un service essentiel devient trop instable, il peut renvoyer `503 Service Unavailable`.

Le message utilisateur reste volontairement léger :

- le serveur est "fatigué"
- il est "un peu étourdi"
- il a décidé de prendre une courte pause

En interne, PulseBeat gère trois états :

- `normal`
- `limp`
- `latched`

#### Mode normal

- toutes les routes fonctionnent normalement
- les compteurs de charge et d'incidents sont observés en arrière-plan

#### Mode limp

Si PulseBeat détecte une surcharge importante mais encore potentiellement récupérable :

- il passe en `limp mode`
- seules les routes les plus légères et utiles à la récupération restent autorisées
- les routes plus lourdes sont rejetées avec `503`
- PulseBeat attend un court délai de refroidissement
- puis essaye automatiquement de revenir en `normal` si la charge est retombée

Le `limp mode` sert à donner une vraie chance de récupération automatique à l'instance sans continuer à accepter aveuglément toute la charge.

#### Mode latched

Si les incidents de surcharge se répètent trop vite ou trop fort :

- PulseBeat passe en `latched`
- l'instance considère alors qu'elle ne peut plus revenir proprement seule à un état sain
- un redémarrage administrateur devient nécessaire

Le mode `latched` ne se retire pas tout seul pendant l'exécution.

#### Comment les admins sont informés

Lors d'une entrée en `limp` ou `latched`, PulseBeat tente de prévenir les admins par plusieurs canaux :

- mise à jour de `system_status` avec l'état courant du watchdog de service
- entrée dans `admin_audit`
- courriel d'alerte admin
- carte d'alerte visible dans le dashboard admin dès que l'interface est consultable

Cela permet :

- une trace persistante côté base
- une alerte visible dans l'interface
- une notification hors bande par courriel

#### Que déclenche concrètement le 503

La décision est basée sur des signaux de surcharge côté instance, par exemple :

- trop de requêtes simultanées
- trop de requêtes sur une courte fenêtre
- accumulation de requêtes anormalement lentes
- certaines erreurs MongoDB non liées au stockage saturé

PulseBeat ne prétend pas détecter un DDoS "parfaitement", mais il essaie de réduire la surface d'impact et de laisser un chemin de récupération avant de demander un redémarrage.

### Erreur 408 : timeout adaptatif et best effort réseau

PulseBeat applique un timeout de base de `20` secondes (`REQUEST_TIMEOUT_SECONDS`).

Cependant, le comportement n'est pas complètement rigide.

#### Cas nominal

Si la requête dépasse le budget de temps autorisé :

- PulseBeat transforme la réponse en `408 Request Timeout` quand cela peut être fait proprement
- surtout sur les lectures / API / routes sûres

#### Connexions lentes mais plausibles

PulseBeat essaie de distinguer une connexion "lente mais raisonnable" d'une connexion plus franchement instable.

Pour cela, il utilise en best effort :

- certains indices de qualité réseau envoyés par le navigateur ou le client quand ils existent
- l'historique récent de temps de réponse du même acteur

Quand le serveur voit plutôt des signaux cohérents avec une connexion lente :

- il donne plus de marge avant timeout
- le budget peut être étendu au-delà des `20` secondes de base

Exemple de logique :

- mode économie de données
- réseau mobile lent
- RTT élevée
- débit annoncé faible

#### Connexions plutôt instables

Si PulseBeat observe au contraire des timeouts ou coupures répétées sans signe crédible d'une simple lenteur stable :

- le budget de temps peut être raccourci
- le `408` peut arriver avant `20` secondes

L'idée est de ne pas laisser une requête monopoliser inutilement des ressources quand le serveur est presque certain qu'il ne s'agit pas d'une simple connexion lente mais d'un flux peu fiable ou cassé.

#### Limites assumées

Le `408` de PulseBeat reste un mécanisme **best effort** :

- Flask ne permet pas d'interrompre magiquement et sans risque n'importe quel traitement serveur déjà bien avancé
- le système fait donc au mieux pour couper proprement les réponses trop longues sans rendre l'application plus fragile

### Erreur 429 : watchdog anti-robot

PulseBeat dispose maintenant d'un watchdog anti-robot destiné à freiner les activités manifestement trop rapides pour être confortablement humaines.

Le message utilisateur garde volontairement une touche d'humour :

- l'utilisateur est "en feu aujourd'hui"
- mais un peu trop vite pour que le serveur suive

#### Philosophie

Le watchdog cherche un équilibre :

- assez strict pour ralentir les scripts agressifs
- assez tolérant pour ne pas punir des utilisateurs normaux ou le trafic légitime du lecteur

Certaines routes naturellement bavardes côté player sont explicitement exclues de cette logique pour éviter les faux positifs.

#### Détection

PulseBeat observe notamment :

- le volume de requêtes sur de courtes fenêtres
- les rafales très compactes
- le volume de requêtes d'écriture
- d'autres signaux d'activité automatisée trop dense

La documentation ne détaille volontairement pas tous les seuils ni tous les critères exacts, afin d'éviter d'offrir un guide de contournement aux robots.

#### Réaction

Au premier niveau :

- PulseBeat renvoie `429`
- un blocage temporaire court peut être appliqué
- un log d'audit et un état admin peuvent être produits

Au second niveau :

- PulseBeat exige une vérification anti-robot avant de laisser l'acteur continuer
- pour un compte connecté, cette exigence peut être mémorisée côté compte
- pour un invité, elle est mémorisée côté session

#### Vérification anti-robot

La vérification actuelle est un challenge simple de type captcha léger / question de contrôle.

Si la vérification réussit :

- les restrictions temporaires sont levées
- l'utilisateur peut reprendre une activité normale

#### Exemption du root admin

Le compte root admin n'est jamais bloqué par le `429` ni par la vérification anti-robot.

Cette exemption est volontaire pour éviter qu'un faux positif verrouille l'accès au compte d'administration principal.

### Honeypot de formulaires

En plus du watchdog 429, PulseBeat ajoute une couche supplémentaire sur les formulaires `POST`.

Chaque formulaire contient désormais au moins un champ caché non fonctionnel, invisible pour un utilisateur normal.

Le README mentionne volontairement l'existence de ce mécanisme, mais ne documente pas l'identité exacte de ces champs.

#### Si le honeypot est déclenché

Pour un compte utilisateur standard :

- le compte est banni automatiquement
- le ban reste en place jusqu'à intervention d'un admin
- la raison de ban stockée est :
  - `Utilisation de scripts automatisé ou d'un robot suspectée`

Cette logique est volontairement plus sévère qu'un simple `429`, car remplir ce type de champ est considéré comme un signal beaucoup plus fort d'automatisation bête ou malveillante.

#### Exception root admin

Le root admin n'est pas auto-banni par ce mécanisme.

L'événement peut être journalisé, mais le compte root reste utilisable pour éviter un blocage administratif accidentel.

### Variables d'environnement associées

- `REQUEST_TIMEOUT_SECONDS`
  - budget de base du timeout applicatif
- `SERVICE_OVERLOAD_ACTIVE_REQUESTS`
  - seuil de requêtes actives simultanées avant réaction watchdog
- `SERVICE_OVERLOAD_BURST_REQUESTS`
  - seuil de rafale sur fenêtre courte
- `SERVICE_BURST_WINDOW_SECONDS`
  - taille de la fenêtre de rafale
- `SERVICE_OVERLOAD_SLOW_REQUESTS`
  - nombre de requêtes lentes tolérées sur la fenêtre lente
- `SERVICE_SLOW_WINDOW_SECONDS`
  - fenêtre d'observation des requêtes lentes
- `SERVICE_LIMP_MODE_SECONDS`
  - durée minimale d'un limp mode avant tentative de récupération
- `SERVICE_LATCH_OVERLOAD_EVENTS`
  - nombre d'événements de surcharge avant passage en `latched`
- `SERVICE_LATCH_WINDOW_SECONDS`
  - fenêtre de comptage des événements de surcharge
- `SERVICE_RECOVER_ACTIVE_REQUESTS`
  - niveau de requêtes actives considéré assez bas pour une récupération
- `SERVICE_RECOVER_BURST_REQUESTS`
  - niveau de trafic récent considéré assez calme pour une récupération
- `ROBOT_WATCHDOG_WINDOW_SECONDS`
  - fenêtre principale du watchdog anti-robot
- `ROBOT_WATCHDOG_MAX_REQUESTS`
  - volume de requêtes toléré sur cette fenêtre
- `ROBOT_WATCHDOG_WRITE_WINDOW_SECONDS`
  - fenêtre d'observation des écritures
- `ROBOT_WATCHDOG_MAX_WRITE_REQUESTS`
  - volume d'écritures toléré sur cette fenêtre
- `ROBOT_WATCHDOG_BURST_WINDOW_SECONDS`
  - fenêtre ultra-courte pour détecter les rafales anormales
- `ROBOT_WATCHDOG_MAX_BURST_REQUESTS`
  - seuil de rafale très dense
- `ROBOT_WATCHDOG_BLOCK_SECONDS`
  - durée de blocage temporaire de premier niveau
- `ROBOT_WATCHDOG_CHALLENGE_BLOCK_SECONDS`
  - durée de blocage pendant une vérification anti-robot

### Ce qui a été étendu dans la dernière passe

La couverture a aussi été élargie aux documents qui servent de support à l'application et qui étaient encore plus "silencieux" :

- les lignes `system_status` utilisées par la zone admin et les alertes de santé
- le document `app_settings` chargé globalement pour les feature flags
- les playlists du header chargées sur toutes les pages pour un utilisateur connecté
- certaines lectures de sécurité côté admin/root admin
- les lots d'historique d'écoute parcourus pendant les routines internes de déduplication, sans suppression préventive au bootstrap

L'intérêt de cette extension est d'éviter qu'un document corrompu dans une collection annexe ou technique ne casse une page entière simplement parce qu'il est consulté partout ou très souvent.

## Comptes Google

Les comptes connectés via Google OAuth ont un comportement spécifique :
- l'adresse e-mail est considérée comme vérifiée par Google
- PulseBeat ne gère pas leur mot de passe
- le bloc de changement de mot de passe n'est pas affiché dans `Gérer mon compte`
- la vérification de mot de passe compromis et le lockout associé ne s'appliquent pas à ces comptes

## Erreurs HTTP

- Les pages d'erreur personnalisées incluent aussi le code `501` (requête non prise en charge).

## Conditions d'usage importantes

PulseBeat est un projet que tu peux utiliser librement dans un cadre **personnel**.

- l'usage personnel est gratuit et le restera toujours
- la modification du code est autorisée
- la modification du code est même encouragée pour adapter PulseBeat à tes besoins

En revanche, par défaut :

- l'usage **commercial** de PulseBeat **sans adaptations significatives du code** est strictement interdit
- toute exploitation commerciale de ce type nécessite une **entente écrite préalable** avec le créateur du projet

Pour toute demande d'entente commerciale, tu peux contacter le créateur à :

- `computerguy020@gmail.com`
- `comeonwindows@mail.com`

En pratique, cela signifie que :

- l'auto-hébergement personnel, les tests, l'apprentissage et les forks personnels sont autorisés
- la revente, la redistribution commerciale ou l'hébergement commercial du projet quasi tel quel ne sont pas autorisés par défaut
- si tu veux utiliser PulseBeat dans un contexte commercial sérieux, il faut d'abord obtenir un accord écrit

Le détail formel de ces conditions figure aussi dans le fichier [LICENSE](LICENSE). En cas de différence d'interprétation, il faut se référer au contenu du fichier de licence présent dans le dépôt.

## Sécurité

- ne jamais versionner le vrai fichier `.env`
- régénérer immédiatement tout secret exposé par erreur
- utiliser un vrai `FLASK_SECRET_KEY`
- utiliser un mot de passe d'application SMTP, pas le mot de passe principal de la boîte mail
