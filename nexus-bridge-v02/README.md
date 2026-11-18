# DOBBY V1 — assistant personnel intelligent

## Préparation du homelab

`homelab_probe.check()` vérifie en lecture seule, via l'alias SSH existant
`nexus-runner`, la présence des lanceurs Codex et Claude aux emplacements
`/home/runner/.local/bin` et du répertoire Git témoin `nexus-test`. La commande
est fixe, SSH vérifie la clé d'hôte connue et n'interagit pas avec l'utilisateur ;
aucun agent ni service n'est lancé. Ce diagnostic n'est pas encore relié à
l'application mobile et ne vérifie ni une session connectée, ni le contenu ou
la validité du dépôt. Claude pourrait être installé ailleurs. Les tests ne
requièrent ni réseau ni compte. Aucun identifiant n'est lu ou recopié.

## Voix locale Piper : préparation

`speech_provider.py` appelle le moteur Piper installé dans
`../outputs/dobby-voix/.venv` dans un processus séparé, sans shell et sans API
payante. Le modèle français est Tom et le modèle anglais Alan. La requête est
bornée à 500 caractères, 30 secondes et un seul processus à la fois ; les WAV
de plus de 3 Mio sont refusés. Le texte et le son ne sont pas consignés, et le
backend ne crée pas de fichier audio. L'endpoint `POST /api/speech` requiert la
session et l'origine DOBBY, et accepte uniquement `text` et `language` (`fr` ou
`en`). L'environnement Piper et les modèles doivent rester à leur emplacement.

L'application mobile préparée demande l'audio en HTTPS privé ; elle l'envoie à
la montre par ChannelClient, sans jeton. L'application montre préparée conserve
le texte, lit le WAV depuis son cache privé puis le supprime ; les fichiers
résiduels portant le préfixe propre à DOBBY sont supprimés au prochain démarrage.
En cas d'indisponibilité, elle utilise son moteur Android. Un sélecteur permet de
choisir Tom ou Alan : le choix ne traduit pas les réponses, qui doivent déjà
être dans la langue voulue. Si le transfert dépasse 45 secondes, le secours est
utilisé. Les échantillons sont dans `../outputs/dobby-voix` ; les licences de
Piper et des modèles y sont documentées.

Les tests automatiques et la génération locale ont été exécutés. Le transfert
et le secours entre le Fold et la montre restent à valider sur appareils. Il ne
faut pas déclarer la voix Piper fonctionnelle sur la montre avant cet essai.

## Préparation Google Agenda

Les dépendances Google sont installables dans l'environnement isolé avec
`.\.venv\Scripts\python.exe -m pip install -r requirements-calendar.txt`.
`calendar_auth.py` prépare une autorisation interactive limitée à la lecture
(`calendar.readonly`). Il cherche `google_credentials.json` dans
`%LOCALAPPDATA%\DOBBY\secrets`, ou un unique fichier `client_secret_*.json` si
le premier nom n'existe pas. Le jeton reçu sera enregistré dans le Gestionnaire
d'identifiants Windows du compte courant, sans fichier de jeton ni inscription
dans SQLite. Ne lancer l'autorisation que lorsque la portée souhaitée est fixée :

```powershell
.\.venv\Scripts\python.exe .\calendar_auth.py
```

Cette commande ouvre une page Google et demande votre consentement. Le module
`calendar_reader.py` consulte en lecture seule l'agenda principal pour les sept
prochains jours, avec dix événements au maximum. `GET /api/calendar/upcoming`
exige une session DOBBY authentifiée et renvoie uniquement le titre et le début.
Une question vocale concernant l'agenda, une journée, une semaine ou des
disponibilités interroge l'agenda et résume jusqu'à quatre événements. Les
disponibilités ne concernent que l'agenda principal, pour la journée demandée,
entre 9 h et 18 h, par créneaux de 30 minutes minimum ; elles ne prouvent pas
la disponibilité d'autres personnes ou agendas. Les dates et heures sont en
Europe/Paris ; les instances récurrentes et les journées entières sont prises en
compte. Les dates peuvent être relatives, un jour de semaine, « 19 novembre »
ou au format `2026-11-19`. Le contenu de l'agenda peut
donc être prononcé à portée d'autres personnes ; le téléphone doit rester
connecté et authentifié. Aucune écriture d'événement n'est implémentée.

Le backend doit être lancé dans l'environnement `.venv` pour accéder aux
bibliothèques Google. Redémarrer le backend local invalide les sessions DOBBY ;
se reconnecter ensuite sur le téléphone. Les tests utilisent des réponses Google
fictives et aucune requête réelle n'est faite avant consentement. La validation
sur l'agenda réel et le parcours mobile restent à effectuer après l'autorisation.

## Mémoire Cuisine

Le coffre unique `../DOBBY` se consulte dans Obsidian en choisissant « Ouvrir
un dossier comme coffre ». Les cinq fiches initiales ne contiennent aucune
recette personnelle non fournie. Leur provenance et les champs manquants sont
indiqués dans chaque fiche. Le dossier a une ACL réservée à l'utilisateur
Windows, au système et aux administrateurs ; les administrateurs ont accès.

`memory.Memory.search(question)` recherche localement les titres, catégories,
ingrédients et autres mots des notes Markdown sous Cuisine ; la recherche ne
suit pas les liens symboliques ou jonctions, limite les fichiers, les résultats
et les extraits, et retourne le nom de la fiche source. Les versions sont des
propriétés ou fichiers Markdown distincts, conservés explicitement par l'utilisateur.
Le point authentifié `POST /api/memory/search` prend `{"query":"chili"}`.
La réponse vocale de simulation cherche aussi dans les fiches et cite leur nom.
Le résultat est un extrait enregistré, pas une suggestion culinaire.

Le point authentifié `POST /api/memory/answer` requiert `--allow-live` et une
confirmation explicite `billing_confirmed: true` par requête. Il envoie au
maximum quatre extraits bornés à Responses, sans historique ni coffre complet,
et reste limité à six appels par processus. C'est une limite logicielle, pas un
plafond de facturation ; elle repart à zéro au redémarrage. Aucun appel n'est
fait par la recherche locale ou le mode vocal simulé. Les extraits sont des
données non fiables ; le modèle peut malgré cela se tromper ou suivre une
injection, et sa réponse doit être vérifiée. Les secrets détectés bloquent
l'envoi ; cette détection n'est pas exhaustive. Ne mettez aucun secret dans
les notes. L'interface mobile ne déclenche pas ce point payant automatiquement.

`Memory.propose_update(source, contenu)` renvoie un diff sans écrire. L'écriture
automatique, son approbation, la sauvegarde et l'historique automatique ne sont
pas encore implémentés ; garder des sauvegardes externes avant les changements
manuels et conserver les versions séparément. Aucune action du modèle ne peut
modifier une note ou exécuter une commande.

Pour importer une conversation Cuisine : exporter vos données ChatGPT, extraire
l'archive dans un emplacement privé, puis ouvrir et rechercher localement la
conversation souhaitée. Relire les messages et ne recopier dans une fiche que
les informations confirmées, avec la provenance et la date ; distinguer les
suggestions de vos propres décisions, retirer tous secrets et compléter les
champs YAML. Conserver l'export hors du coffre et ne jamais le transmettre
automatiquement. En cas d'incertitude, laisser la rubrique « non renseigné ».

Pour activer le nouveau code local, redémarrer le serveur DOBBY de développement ;
les sessions expirent au redémarrage. Ensuite se reconnecter sur le téléphone et
demander depuis la montre « retrouve ma recette de chili ». Le parcours complet
sur appareils avec ces nouvelles fiches reste à vérifier. Le mode OpenAI exige
une autorisation distincte des frais et une interface client de confirmation ;
la commande vocale existante ne l'active pas.

## Interface web locale

`python web_server.py` démarre DOBBY sur `http://127.0.0.1:8765/`, en mode
simulation uniquement. À la première ouverture web ou mobile, saisir `000000` :
ce code fixe déclenche uniquement la configuration initiale. DOBBY demande alors
un nouveau PIN personnel deux fois ; `000000` ne peut pas être conservé comme
PIN final. Cette initialisation est à usage unique. Tout appareil pouvant joindre
l'adresse privée avant cette configuration pourrait tenter de la réclamer :
garder l'accès réseau privé et terminer la configuration au premier démarrage.
Le script local `python set_pin.py` permet aussi de définir ou remplacer le PIN,
avec saisie masquée. Le PIN personnel est conservé sous forme d'empreinte scrypt
salée dans `.dobby-local/missions.sqlite3`, ignoré par Git, sans PIN en clair.
Après cinq échecs consécutifs, les connexions sont bloquées pendant 15 minutes,
y compris après redémarrage. Le changement du PIN invalide les sessions ; elles
expirent aussi après huit heures. Ne pas communiquer le PIN dans une commande,
un message ou un journal. Un PIN à six chiffres reste vulnérable à une attaque
hors ligne si une personne obtient une copie de la base ; protéger le PC et le
répertoire, et limiter les appareils autorisés sur le tailnet.
Après configuration sur mobile, seul le cookie de session est stocké chiffré par
Android Keystore. Le téléphone transmet les états de missions à la montre appairée
via Wearable Data Layer ; le PIN et le cookie ne sont jamais transmis à la montre.
Une mission simulée attend une approbation authentifiée avant de continuer.

Pour préparer un proxy Tailscale Serve HTTPS privé, démarrer le serveur avec
`--origin https://NOM-DE-LA-MACHINE.NOM-DU-TAILNET.ts.net` puis, après avoir
vérifié la configuration Serve existante, utiliser Tailscale Serve sur le port
8765. Ne pas utiliser Funnel. Le serveur reste lié à `127.0.0.1`. Le nom HTTPS
est une origine supplémentaire autorisée ; l'origine locale reste disponible.
Tailscale Serve, les certificats HTTPS et les règles du tailnet doivent être
configurés séparément par l'utilisateur. Un manifeste permet l'installation
depuis un navigateur compatible, mais aucun fonctionnement hors ligne n'est
promis.

Le mode réel n'est disponible que si le serveur est lancé explicitement avec
`--allow-live`, que la clé API est déjà disponible côté serveur et que la
connexion ChatGPT Codex est configurée. Une confirmation de facturation est
requise à la création et une approbation authentifiée avant chaque appel Codex.
Seule la mission témoin en lecture seule est acceptée. Les limites logicielles
ne garantissent pas un plafond de facturation. L'interface réelle n'a été
testée qu'avec des agents simulés ; aucune requête facturable n'a été envoyée.

DOBBY est un assistant personnel inspiré de l'idée d'un elfe de maison libre,
lié à l'univers littéraire de son créateur. Il réunit un Architecte OpenAI et
Codex CLI pour collaborer sur des missions encadrées.

## Architecte OpenAI et Codex local

Dans PowerShell, configurer `OPENAI_API_KEY` dans l'environnement de la session
par un moyen privé, puis lancer :

```powershell
python demo.py --architect openai
```

La commande demande d'abord la confirmation de la clé, des paramètres de
facturation et de l'essai API. Elle demande ensuite une approbation avant
**chaque** appel Codex, y compris après une révision. Sans cette confirmation,
aucune requête API n'est envoyée ; sans l'approbation Codex, Codex ne démarre
pas. Le modèle configuré par défaut est `gpt-6-luna` ; `--model gpt-6.1-terra`
est également accepté par le programme. Leur disponibilité dépend du compte API.
`python demo.py` conserve l'Architecte simulé.

L'Architecte utilise l'API Responses avec `store=false` et des schémas JSON
stricts ; la seule tâche Codex autorisée reste `analyze:nexus-test`. Les clés ne
sont ni incluses dans les messages ni transmises au processus Codex. Les erreurs
de transport sont remplacées par des codes fixes. Les réponses contenant la clé
ou des motifs de secrets sont refusées, sans garantir la détection de tout secret.
La base locale temporaire est supprimée à la fin de la démonstration ; elle peut
contenir des propositions et conclusions du modèle, à traiter comme sensibles.

Par défaut, le dialogue autorise au plus trois cycles, six appels API, 256 tokens
de sortie par appel, 20 secondes par requête API et 120 secondes par appel Codex.
Il réserve 0,02 USD par appel API sur un budget logiciel de 0,12 USD. Ces montants
sont des réservations prudentes choisies pour l'application, pas une mesure des
coûts réels ni un plafond de facturation garanti ; contrôler les tarifs et les
limites du fournisseur séparément. En cas d'annulation ou d'expiration, une
requête déjà transmise peut continuer et être facturée. L'attente d'approbation
n'est pas comptée dans le temps d'exécution.

Le dialogue réel Architecte–Codex n'a pas encore été exécuté : les tests API et
Codex de cette version utilisent des réponses simulées. L'accès à l'API exige une
clé et des paramètres de facturation actifs, distincts de la connexion ChatGPT.

## Démonstration locale Windows

Depuis PowerShell, dans ce répertoire :

```powershell
python demo.py
```

La commande vérifie l'empreinte du fichier témoin, détecte l'installation
locale de Codex et vérifie que son statut indique une connexion ChatGPT. Elle
crée un dépôt Git témoin temporaire, puis affiche la demande de l'Architecte
**simulé**. Répondre exactement `oui` à l'invite autorise un appel Codex réel ;
toute autre réponse arrête la démonstration avant l'appel. Codex reçoit une
instruction fixe et `--sandbox read-only`, puis sa réponse structurée est
contrôlée avant l'évaluation simulée et l'affichage de la conclusion. Le
répertoire témoin est vérifié avant et après l'appel et est temporaire.

La session Codex existante est utilisée par le programme Codex lui-même. Le
Bridge ne lit ni ne copie les fichiers d'identifiants ; les variables explicites
`OPENAI_API_KEY`, `CODEX_API_KEY` et `CODEX_ACCESS_TOKEN` ne sont pas transmises.
Les configurations et protections Codex existantes ne sont pas désactivées. La
limite est de trois tours et 120 secondes pour l'appel. La sortie brute est
validée en mémoire et non conservée ; seules les catégories autorisées passent.

Cette variante Windows utilise la sandbox Codex installée, et non Bubblewrap.
Elle refuse de contourner cette protection en cas d'échec. Le contrôle de hash
détecte une modification persistante du témoin mais ne démontre pas à lui seul
que la sandbox interdit toute écriture. Le fonctionnement de la sandbox, de
l'authentification et du schéma avec une mission réelle reste à valider lors
d'un appel autorisé. L'évaluation est simulée, pas une revue par un modèle IA.
Le délai ne garantit pas un plafond de facturation ; la sortie du modèle peut
échouer à la validation. Cette démonstration ne touche pas aux services existants.

## Anciens noms techniques conservés

Le répertoire du projet reste `nexus-bridge-v02`. Le dépôt témoin `nexus-test`,
l'identifiant de tâche `analyze:nexus-test` et la variable de test
`NEXUS_RUN_OFFLINE_BWRAP_TEST` restent inchangés pour préserver la compatibilité.
Les chemins, unités et sockets historiques NEXUS Runner et Gateway ne sont pas
renommés ; ils sont distincts de l'identité de DOBBY et ne sont pas modifiés.
Les rapports historiques conservent leurs noms techniques pour rester fidèles
aux vérifications effectuées.

Prototype local Python 3.12+, sans dépendance Python externe. Il simule un architecte,
un exécutant et une révision, avec persistance SQLite et approbation humaine
entre proposition et exécution. Par défaut il ne contacte aucun service et ne
lance aucune commande. Ce n'est pas un système prêt pour la production.

## Démarrage

```text
python -m unittest -v
python main.py --db bridge.sqlite3 create "Améliorer la documentation"
python main.py --db bridge.sqlite3 run UUID
python main.py --db bridge.sqlite3 show UUID
python main.py --db bridge.sqlite3 approve UUID
python main.py --db bridge.sqlite3 run UUID
```

Remplacer `UUID` par l'identifiant retourné. Le premier `run` produit une
proposition et s'arrête en `awaiting_approval`. Après approbation, le second
simule l'exécution et la révision, puis termine en `completed`. Une révision
`revise` déclenche une nouvelle proposition et une nouvelle approbation.
L'approbation est une opération locale, sans authentification : l'accès au
fichier SQLite et au programme doit être réservé à l'opérateur de confiance.

## Protocole JSON v0.2

Les messages échangés entre adaptateurs sont des objets JSON à schéma fermé :

```json
{"type":"proposal","summary":"Résumé du plan","task":"Tâche proposée"}
{"type":"result","summary":"Résultat de l'exécutant"}
{"type":"review","decision":"accept","summary":"Conclusion"}
```

`decision` vaut `accept` ou `revise`. Les champs supplémentaires, notamment
`command`, sont rejetés. Le texte `task` est une instruction de travail, pas
une commande shell ; il n'est jamais interprété par un shell. Le journal ordonné des
messages et les états sont dans les tables `messages` et `missions`.

## Limites et reprise

`Limits` borne les appels aux agents, le temps cumulé d'attente des adaptateurs,
la taille d'une entrée ou d'un message JSON UTF-8, les octets cumulés et un
budget d'unités simulées. La période d'attente de l'approbation et les accès
SQLite ne sont pas inclus dans le temps. Les unités de coût ne sont pas des
euros ou des dollars et ne contrôlent aucune facturation réelle.

Les états sont `ready`, `running`, `awaiting_approval`, `completed`, `failed`.
Un appel est comptabilisé avant son lancement. Une interruption durant un appel
produit `failed` avec `interrupted_unknown_outcome` : aucune action incertaine
n'est rejouée. Après arrêt brutal, l'opérateur peut lancer `recover UUID` pour
marquer un état `running` comme échec, uniquement après avoir vérifié qu'aucun
autre processus ne travaille sur cette mission. Les missions en attente
d'approbation ou `ready` peuvent être reprises normalement. Il n'y a ni bail
distribué ni reprise automatique des appels interrompus.

## Adaptateurs réels et sécurité

`SimulatedArchitect` et `SimulatedExecutor` restent les adaptateurs par défaut.
L'Architecte Responses est activé explicitement par `--architect openai` ;
`LiveAdapterDisabled` reste fermé. Le
adaptateur `codex_adapter.CodexReadOnly` est désactivé par défaut. Il n'accepte
que la tâche exacte `analyze:nexus-test`, ignore l'historique et construit une
instruction et des arguments fixes, sans shell. Seul le répertoire factice
`nexus-test` est monté dans `/workspace`. L'activation explicite en Python est
`CodexReadOnly(CodexConfig(enabled=True))` ; elle ne change pas les défauts de
la CLI de simulation.

L'adaptateur exige Linux et `/usr/bin/bwrap`. Le chemin absolu canonique du
binaire et son SHA-256 doivent être fournis par l'opérateur dans `CodexConfig`
; les liens symboliques, permissions non sûres et empreintes divergentes sont
refusés. Le fichier est ouvert et son descripteur est monté en lecture seule,
sans exposer le répertoire personnel où il se trouve. La provenance doit être
vérifiée indépendamment ; une empreinte relevée sur une machine n'est pas une
preuve d'origine. Il utilise
un espace de montage bubblewrap limité, avec les fichiers système nécessaires et
le dépôt en lecture seule, et `codex exec --sandbox read-only`. Il borne chaque
appel à 30 secondes et 4096 octets au maximum ; l'opérateur peut choisir des
limites inférieures. L'environnement est réduit à PATH, HOME, CODEX_HOME et LANG ;
stderr est écarté et les erreurs ne reprennent pas le texte du processus. Aucune
variable de jeton n'est transmise. La sortie standard brute n'est pas enregistrée :
un objet JSON à schéma fermé est exigé et seules des catégories prédéfinies sont
converties en libellés fixes. Les champs inconnus, le texte libre, les doublons
et les valeurs inconnues entraînent un refus avant stockage. La sortie valide
reste un canal d'information limité ; ce filtrage ne garantit pas qu'un modèle
ne puisse divulguer une information par choix de catégories ou par un autre canal.

Le montage a été testé avec des processus factices, pas avec Codex. La politique
réseau est indépendante : `network='offline'` par défaut utilise `--unshare-net`,
`network='online'` est explicite et ne filtre pas les destinations. En ligne,
un modèle peut recevoir le contenu du dépôt factice.
Le profil utilise un HOME et un CODEX_HOME temporaires vides : il ne fournit ni
authentification ni configuration fournisseur et un vrai lancement peut donc
échouer. Ne pas contourner cet isolement avec des secrets ou une configuration
globale. Le budget de simulation ne limite pas la facturation réelle ; les
permissions, outils système, sandbox Codex et isolation réseau ne sont pas
garantis dans tous les environnements. Un processus Python hostile hors de
l'adaptateur n'est pas confiné.

Les identifiants ne sont pas encore pris en charge. Une piste à concevoir est un
service d'authentification isolé délivrant au seul processus Codex un jeton à
durée et portée minimales, sans passage par l'Architecte ni SQLite ; il faudra
prouver l'identité du processus, protéger le canal et maîtriser les journaux et
la durée de vie. Aucun mécanisme de ce type n'est implémenté, et l'exécution sous
un même UID ne constitue pas une séparation de sécurité suffisante.

### Procédure préparatoire pour un premier essai réel

1. Obtenir une autorisation distincte précisant fournisseur, budget et cadre de
   facturation ; établir un plafond opposable côté fournisseur. Ne pas utiliser
   le budget simulé comme plafond monétaire.
2. Sur un hôte Linux isolé et non opérationnel, vérifier les versions et les
   chemins fixes bubblewrap/Codex, la disponibilité de leur sandbox et la
   compatibilité de l'authentification avec le HOME temporaire. Concevoir et
   valider séparément tout accès aux credentials ; ne pas les placer dans le
   dépôt, les journaux ou les variables transmises par l'adaptateur.
3. Examiner le contenu de `nexus-test` et vérifier qu'il ne contient ni secrets
   ni liens vers des ressources externes. Refaire, sur cet hôte, des essais sans
   Codex de création, modification et suppression refusées dans `/workspace`.
4. Dans une base de test privée, créer une mission dont la tâche est exactement
   `analyze:nexus-test`. Exécuter le plan simulé, examiner la proposition et
   l'approuver explicitement. Injecter ensuite l'adaptateur activé dans
   `Orchestrator(store, executor=CodexReadOnly(CodexConfig(enabled=True)))`.
5. Après autorisation distincte seulement, lancer un appel, surveiller le délai
   et le coût réel, puis examiner le résultat en évitant de le diffuser. Vérifier
   l'intégrité du dépôt avant/après et arrêter l'essai au moindre écart.

Cette procédure n'a pas été exécutée ; aucune garantie de fonctionnement de
l'authentification ni du confinement Codex réel n'est revendiquée.

La base contient des instructions et résultats potentiellement sensibles. La
placer dans un répertoire privé, protéger les sauvegardes et ne pas la publier.
Le prototype ne chiffre pas la base et ne gère ni utilisateurs ni contrôle
d'accès ; ne pas lui confier de secrets. Aucune garantie d'isolation contre un
adaptateur Python malveillant n'est fournie.
