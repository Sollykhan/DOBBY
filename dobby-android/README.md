# DOBBY — Android et Wear OS

Projet Android Studio comprenant `mobile` (téléphone/tablette pliable) et `wear`
(montre Wear OS), avec le même identifiant d'application pour la Data Layer.
La connexion au backend se fait uniquement en HTTPS vers un nom `.ts.net` ; le
serveur DOBBY et Tailscale Serve doivent déjà être configurés sur le PC. Aucun
serveur, compte ou réglage Tailscale n'est modifié par cette application.

## Utilisation

### Calendriers Android

Dans DOBBY connecté, « Calendriers du téléphone » demande la permission de
lecture uniquement après « Vérifier les calendriers ». Cocher uniquement les
calendriers à partager avec DOBBY ; aucun n'est coché par défaut. Le diagnostic
affiche localement leur nombre d'occurrences sur les deux années autour de la
date actuelle, sans transmettre leurs détails. Un zéro peut aussi signifier
qu'aucune occurrence ne tombe dans cette période.

Pour les questions d'agenda depuis la montre ou le bouton « Demander à DOBBY »
du téléphone, DOBBY demande au backend la période pertinente, lit les
occurrences des calendriers cochés et en transmet les champs nécessaires au
backend privé via HTTPS. Ils ne sont pas envoyés à OpenAI. Le backend les fusionne
avec l'agenda Google principal ; les doublons sont retirés uniquement lorsque
titre, début et fin correspondent exactement. Les événements récurrents sont
dépliés par CalendarContract.Instances ; les journées entières utilisent leurs
dates et le fuseau Europe/Paris. Une période contenant plus de 20 occurrences
Android est refusée, afin d'éviter une réponse incomplète. En cas de refus de
permission ou de fournisseur indisponible, la question échoue sans ignorer ces
calendriers. Aucun événement n'est créé ni modifié. Décocher un calendrier pour
cesser de le transmettre ; la permission Android peut être révoquée dans les
paramètres du téléphone.

Le diagnostic local FamilyWall compte les occurrences sans afficher leurs détails.
Le parcours complet avec les versions finales reste à vérifier
sur les appareils ; les calendriers sélectionnés et l'affichage du résultat
doivent être contrôlés par l'utilisateur, sans communiquer leurs détails.

### Carte DOBBY sur la montre

Depuis le cadran, faire défiler les cartes jusqu'à « Ajouter », puis sélectionner
DOBBY. Un appui long sur une carte ouvre normalement leur réorganisation : déplacer
DOBBY au premier emplacement après le cadran. Les libellés et les gestes peuvent
varier selon la version Wear OS ; l'application Galaxy Wearable sur le téléphone
permet aussi de gérer l'ordre des cartes. Le bouton « Parler » ouvre DOBBY et
démarre l'écoute, après permission du microphone si nécessaire. La carte montre
les dernières données reçues ; après 15 minutes sans mise à jour, leur connexion
est indiquée comme indisponible. Aucune écoute permanente n'est activée.

1. Connecter le téléphone à son tailnet avec l'application Tailscale officielle.
   DOBBY détecte un VPN actif et si l'application Tailscale est installée, mais
   ne peut pas prouver qu'un VPN actif est celui de Tailscale ; la disponibilité
   réelle est vérifiée par la connexion HTTPS au backend.
2. Lors de la première configuration seulement, ouvrir DOBBY sur le téléphone,
   vérifier l'adresse HTTPS et saisir `000000`. L'application demande alors un
   nouveau PIN personnel à six chiffres et sa confirmation. Ce code fixe ne peut
   pas devenir le PIN final ; l'initialisation ne réussit qu'une fois et cinq
   essais erronés bloquent les tentatives pendant 15 minutes. Une fois connecté,
   le PIN n'est pas stocké : seul le cookie de session est chiffré avec Android
   Keystore. La sauvegarde Android est désactivée. Le cookie expire côté serveur
   et il faudra alors se reconnecter. Le script `python set_pin.py` sur le PC
   permet aussi de définir ou remplacer le PIN. Après connexion, le téléphone
   synchronise les états des missions avec la montre appairée ; le PIN et le
   cookie ne lui sont jamais transmis.
3. Créer une mission simulée et ouvrir son détail. Chaque approbation passe par
   une confirmation sur le téléphone. Le mode réel n'est proposé que si le
   backend l'autorise, puis exige une confirmation de facturation explicite.
4. Installer la même version signée sur la montre. Elle demande les dernières
   missions au téléphone par Wearable Data Layer. Une demande d'approbation est
   confirmée sur la montre, puis doit **encore être confirmée sur le téléphone** ;
   la montre ne peut pas exécuter directement l'approbation.

La dictée utilise l'interface de reconnaissance vocale présente sur l'appareil
pour produire une note affichée ; elle ne crée ni n'approuve une mission. Elle
peut dépendre du service vocal choisi par l'utilisateur. Les notifications
nécessitent l'autorisation Android : la vérification en arrière-plan utilise
WorkManager (environ 15 minutes ou plus, selon Android). La synchronisation
montre utilise MessageClient : elle exige un téléphone appairé et connecté,
n'offre ni file persistante ni garantie de livraison hors ligne.

## Ouvrir et compiler

Ouvrir ce répertoire dans Android Studio, utiliser JDK 17 ou 21 et le SDK Android
34, puis synchroniser Gradle. La compilation télécharge les dépendances depuis
Google Maven et Maven Central. En ligne de commande avec le wrapper inclus :

```powershell
.\gradlew.bat :mobile:assembleDebug :wear:assembleDebug :mobile:testDebugUnitTest
```

Les APK de débogage, s'ils sont produits, se trouvent sous
`mobile/build/outputs/apk/debug/` et `wear/build/outputs/apk/debug/`. Ce sont
des builds de développement signés avec la clé de debug locale, non publiés.

## Installation ADB, sans Play Store

Sur chaque appareil, activer les options développeur et le débogage USB ou sans
fil, puis accepter l'association ADB sur l'appareil. Vérifier avec
`adb devices -l`, puis installer les APK sur les identifiants respectifs :

```powershell
adb -s SERIAL_TELEPHONE install -r mobile\build\outputs\apk\debug\mobile-debug.apk
adb -s SERIAL_MONTRE install -r wear\build\outputs\apk\debug\wear-debug.apk
```

Pour le débogage sans fil, l'association `adb pair ADRESSE:PORT_ASSOCIATION` et
la connexion `adb connect ADRESSE:PORT_DEBOGAGE` sont à faire avec les valeurs
affichées par l'appareil. Ne pas communiquer les codes d'association. Les deux
applications doivent porter le même identifiant et être signées avec la même
clé pour que la Data Layer fonctionne. Aucune installation n'est automatique.

## Limites de sécurité et de validation

Les API et missions réelles n'ont pas été appelées pendant le développement.
Le backend conserve ses règles : une seule tâche autorisée, contrôle du contenu
et approbation. Les données reçues et le statut sont montrés sur la montre ; ne
pas utiliser d'appareil partagé pour des missions sensibles. La session côté
serveur est liée au temps et le téléphone doit conserver le contrôle de son
écran ; un appareil déverrouillé peut autoriser des actions. Aucun mécanisme
biométrique supplémentaire n'est mis en place. Le débogage ADB doit être
désactivé après installation si non nécessaire.

## Validation de ce build

Mise à jour PIN : l'APK mobile utilise un clavier numérique et refuse les PIN
qui ne contiennent pas exactement six chiffres ASCII. Trois tests unitaires ont
réussi et l'APK a été mis à jour sur le Fold 7. Le protocole HTTPS existant est
inchangé ; la saisie du PIN personnel reste à effectuer par l'utilisateur.

La compilation de `:mobile:assembleDebug`, `:wear:assembleDebug` et
`:mobile:testDebugUnitTest` a réussi avec Gradle 8.13 et JDK 21. Les deux tests
unitaires de validation des adresses et des identifiants de mission ont réussi.
L'APK mobile a été installé et lancé sur le Galaxy Z Fold 7 connecté en ADB.
Le serveur local et sa route HTTPS Tailscale Serve ont répondu sans requête de
mission réelle. La connexion authentifiée, les écrans plié/déplié, les
notifications et la synchronisation avec une montre physique restent à tester
sur les appareils. L'APK Wear a également été installé et lancé sur la Galaxy
Watch 4 ; l'autorisation des notifications est demandée par Android.
