# PulseBeat

Application de streaming musical en `Flask` + `Jinja`, inspirée de YouTube Music, avec lecteur flottant, comptes utilisateurs, playlists collaboratives, espace admin, i18n FR/EN et stockage MongoDB.

## Fonctionnalités

- Comptes utilisateurs locaux avec confirmation du mot de passe
- Vérification d'adresse e-mail obligatoire avant connexion
- Connexion Google OAuth
- Les comptes Google ne gèrent pas leur mot de passe dans PulseBeat : pas de changement de mot de passe local, pas de lockout lié aux mots de passe compromis
- Authentification 2 facteurs (2FA) optionnelle par code courriel pour les comptes locaux
- Activation/désactivation de la 2FA confirmée par courriel puis mot de passe
- Réinitialisation de mot de passe par e-mail
- Avertissement à l'inscription pour e-mail temporaire avec confirmation explicite avant création du compte
- Vérification des mots de passe compromis
- Verrouillage progressif de connexion par adresse e-mail après échecs répétés (6 tentatives), avec durée doublée à chaque cycle
- Envoi automatique d'un e-mail de déverrouillage après verrouillage, avec lien sécurisé de déverrouillage + connexion
- Changement de mot de passe et lock de sécurité si mot de passe compromis
- Changement du nom d'utilisateur depuis `Gérer mon compte`, avec validation JavaScript en direct + validation serveur
- Invalidation globale des sessions après changement ou réinitialisation de mot de passe
- Protection anti-vol de session par appareil de confiance + approbation par courriel des nouveaux appareils
- Invalidation des sessions suspectes si un cookie semble rejoué depuis un autre environnement
- Écran de blocage de session suspecte renforcé avec bandeau d'avertissement visuel, animation d'alerte et tentative de son d'avertissement au chargement
- Ajout de chansons par URL ou upload (avec détection automatique des balises ID3)
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
- Lecteur avec vues `mini`, `normale` et `plein écran`
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
- Partage externe des chansons/playlists publiques ou non répertoriées (copie de lien + plateformes)
- Préférences utilisateur pour exclure des chansons ou artistes des recommandations
- Recommandations v2 équilibrées (mix préférences personnelles + populaires + découverte)
- Statistiques créateur dans `Gérer mon compte` (écoutes, likes/dislikes, top chansons)
- Abonnements publics aux créateurs avec désabonnement, compteur d'abonnés et notifications internes de nouvelles publications via la cloche PulseBeat
- Panneau de notifications de publication responsive et utilisable sur mobile
- Détection des doublons audio à l'upload via fingerprint SHA-256
- Export des données de compte en JSON et CSV
- Synchronisation de bibliothèque externe YouTube avec import de playlists (fonctionnelle), avec lecture partielle de certaines pistes selon les limites YouTube/Google
- Notifications e-mail lors des partages de playlist
- Recherche, suggestions, tri et pagination (incluant recherche insensible à la casse dans les paroles)
- Profils publics utilisateurs avec chansons et playlists accessibles selon les permissions
- Validations JavaScript en direct sur les formulaires, avec validation serveur conservée
- Blocage complet du site si JavaScript est désactivé
- Sources JavaScript conservées lisibles côté projet, avec bundles obfusqués servis au navigateur
- Unicité des `username` et `email` garantie côté serveur et par index MongoDB
- Zone admin séparée
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

## Recherche avancée (accueil + playlists)

La recherche de chansons couvre maintenant les champs suivants :

- `title`
- `artist`
- `genre`
- `lyrics_text` (paroles)

Détails importants :

- toutes ces recherches sont faites en mode **non sensible à la casse** (`case-insensitive`)
- la recherche d'accueil utilise ces critères dans la requête principale de listing
- la recherche interne d'une playlist (`songs_q`) applique aussi ces critères
- les suggestions de recherche (globales et dans playlist) incluent aussi les paroles

Effet pratique : un mot présent dans les paroles peut faire ressortir une chanson même si ce mot n'est pas dans le titre ou l'artiste.

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

## Authentification 2 facteurs (2FA)

### Vue d'ensemble

PulseBeat propose une 2FA **optionnelle** pour les comptes locaux (non Google).  
Quand elle est activée, une connexion par mot de passe nécessite aussi un **code de vérification à 6 chiffres envoyé par courriel**.

Important :
- les comptes Google ne peuvent pas activer la 2FA PulseBeat (la 2FA est gérée côté Google)
- la 2FA locale s'applique uniquement après une authentification primaire correcte (email/username + mot de passe)

### Comment activer la 2FA

1. Aller dans `Gérer mon compte` > section `Authentification 2 facteurs`.
2. Cliquer `Activer la 2FA`.
3. PulseBeat envoie un **courriel de confirmation** contenant un lien signé temporaire.
4. Ouvrir ce lien puis entrer le **mot de passe actuel** pour finaliser.
5. La 2FA passe à l'état `activée`.

Après la création d'un compte local, PulseBeat affiche aussi un modal de recommandation pour encourager l'activation.

### Comment désactiver la 2FA

Le flux est symétrique à l'activation :
1. Cliquer `Désactiver la 2FA`.
2. Confirmer via le lien reçu par courriel.
3. Entrer le mot de passe actuel sur l'écran de confirmation.
4. La 2FA passe à l'état `désactivée`.

### Technique 2FA utilisée

- code OTP numérique à `6` chiffres (`TWO_FACTOR_CODE_LENGTH = 6`)
- code généré côté serveur via `secrets.randbelow(...)`
- le code n'est **pas stocké en clair** en session :
  - PulseBeat stocke un hash SHA-256 basé sur `user_id + code + FLASK_SECRET_KEY`
- durée de validité du code configurable via `TWO_FACTOR_CODE_MAX_AGE` (défaut `600` secondes)
- page challenge dédiée (`/two-factor/challenge`) avec possibilité de renvoyer un nouveau code

### Mauvais code / trop de tentatives

- chaque code invalide incrémente un compteur en session
- message utilisateur avec le nombre de tentatives restantes
- limite stricte : `6` erreurs (`TWO_FACTOR_CODE_MAX_ATTEMPTS = 6`)
- à la limite atteinte :
  - session 2FA invalidée
  - retour à la page de connexion
  - il faut recommencer le login pour obtenir un nouveau code
- si le code expire, même comportement : challenge invalidé et retour login

### Confirmation par courriel pour activation/désactivation

Les opérations sensibles d'activation/désactivation 2FA exigent :
- un **lien signé temporaire** envoyé par courriel (`TWO_FACTOR_TOGGLE_TOKEN_MAX_AGE`, défaut `3600` secondes)
- puis une **vérification du mot de passe**

Cela réduit les risques de bascule 2FA non autorisée même si la session web est déjà ouverte.

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
- JavaScript vanilla
- HTML / CSS

## Structure du projet

- `app.py` : création de l'application Flask, config, startup
- `extensions.py` : connexion MongoDB et collections
- `auth_helpers.py` : helpers auth, sécurité, mail, permissions
- `blueprints/accounts.py` : auth, setup initial, reset password, vérification e-mail, Google OAuth, profils publics
- `blueprints/main.py` : accueil et navigation principale
- `blueprints/songs.py` : chansons, détails, votes, commentaires, signalements
- `blueprints/playlists.py` : playlists, collaborateurs, recherche, partage
- `blueprints/admin.py` : dashboard admin
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
- `data_exports`
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

### 2FA (optionnel, recommandé)

Variables disponibles :
- `TWO_FACTOR_CODE_MAX_AGE=600` (durée de validité du code 2FA, en secondes)
- `TWO_FACTOR_TOGGLE_TOKEN_MAX_AGE=3600` (durée de validité du lien de confirmation activation/désactivation 2FA, en secondes)
- `TWO_FACTOR_TOGGLE_SALT=pulsebeat-two-factor-toggle` (salt du token de confirmation 2FA)

### Sessions liées aux appareils (optionnel, recommandé)

Variables disponibles :
- `DEVICE_COOKIE_NAME=pulsebeat_device_id` (nom du cookie d'appareil PulseBeat)
- `DEVICE_COOKIE_MAX_AGE=31536000` (durée de vie du cookie d'appareil, en secondes)
- `DEVICE_APPROVAL_TOKEN_MAX_AGE=1800` (durée de validité du lien d'approbation d'un nouvel appareil)
- `DEVICE_APPROVAL_SALT=pulsebeat-device-approval` (salt du token d'approbation d'appareil)

### JavaScript client (optionnel)

Variables disponibles :
- `JS_SERVE_OBFUSCATED=1` (sert les bundles obfusqués du dossier `static/dist/` si disponibles)

Comportement :
- si la variable vaut `1` et que les bundles existent, PulseBeat sert `static/dist/*.obf.js`
- sinon, PulseBeat retombe automatiquement sur les sources lisibles de `static/js/`
- cela permet de garder un workflow simple en développement tout en réduisant l'exposition des sources côté navigateur

### Sync bibliothèque YouTube (optionnel)

Pour activer la connexion de bibliothèques externes depuis `Gérer mon compte` :

- `YOUTUBE_SYNC_CLIENT_ID=...`
- `YOUTUBE_SYNC_CLIENT_SECRET=...`

Sans ces variables, les boutons d'intégration restent visibles mais marqués `Non configuré`.

État actuel de la fonctionnalité :

- la synchronisation YouTube fonctionne bien (connexion OAuth, récupération des playlists, import dans PulseBeat)
- la lecture des chansons importées depuis YouTube fonctionne pour certaines pistes uniquement
- selon les titres, la lecture peut échouer à cause de restrictions côté YouTube/Google API (droits, disponibilité, limitations d'accès/embeds), ou de limites techniques côté PulseBeat sur les sources externes

Détails techniques de l'import :

- synchronisation OAuth vers les collections :
  - `external_integrations` (tokens)
  - `external_playlists` (playlists + tracks externes)
- import en playlist locale non bloquant :
  - la création démarre immédiatement
  - le traitement est délégué à un worker en arrière-plan
  - timeout court côté requête utilisateur (~2.8s), puis message "continue en arrière-plan"
  - la playlist locale expose `import_status` (`pending`, `running`, `completed`, `failed`)
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

## Comptes Google

Les comptes connectés via Google OAuth ont un comportement spécifique :
- l'adresse e-mail est considérée comme vérifiée par Google
- PulseBeat ne gère pas leur mot de passe
- le bloc de changement de mot de passe n'est pas affiché dans `Gérer mon compte`
- la vérification de mot de passe compromis et le lockout associé ne s'appliquent pas à ces comptes

## Erreurs HTTP

- Les pages d'erreur personnalisées incluent aussi le code `501` (requête non prise en charge).

## Sécurité

- ne jamais versionner le vrai fichier `.env`
- régénérer immédiatement tout secret exposé par erreur
- utiliser un vrai `FLASK_SECRET_KEY`
- utiliser un mot de passe d'application SMTP, pas le mot de passe principal de la boîte mail
