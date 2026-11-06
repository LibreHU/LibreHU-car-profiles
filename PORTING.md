# Porter une voiture

Ce guide explique comment écrire la **fiche** d'une voiture pour LibreHU : le fichier qui dit au moteur de
LibreHU service comment parler au boîtier CAN de la voiture et où se trouve chaque valeur dans ses messages.
Pas besoin de savoir programmer : une fiche est un fichier JSON, vérifié automatiquement.

Format complet : [docs/can-vehicles.md](https://github.com/LibreHU/LibreHU-service/blob/main/docs/can-vehicles.md)
(§ Format, § Format 2). Fonctionnement : [page « Moteur voiture »](https://librehu.github.io/engine.html).

## 0. Ce qu'il faut

- L'autoradio avec **LibreHU service** et le boîtier CAN de la voiture branché.
- Savoir quel **boîtier** c'est : fabricant (Hiworld, Raise, Simple, Oudi, Binary…) et, si possible, le code de
  protocole (étiquette du boîtier ou réglages de son appli d'origine, par exemple `LNP002`, `VWP004`).
- Un ordinateur avec Java 17 pour tester la fiche sans la voiture (facultatif mais conseillé) :
  [`librehu-car-tool.jar`](https://github.com/LibreHU/LibreHU-service/releases/download/latest-main/librehu-car-tool.jar).

## 1. Capturer

1. Onglet **CAN** de LibreHU service → profil **brut** du fabricant de votre boîtier (`hiworld-generic` pour Hiworld).
2. Actionner les commandes **une par une**, en notant l'heure : chaque touche du volant, chaque porte, les feux, la
   marche arrière, le frein à main, tourner le volant à fond à gauche puis à droite, la clim…
3. **Exporter** (bouton de l'onglet CAN) : un fichier texte, une ligne par message (`HH:MM:SS.mmm  CC: DD DD …`).

## 2. Repérer

Dans l'onglet CAN, les octets qui changent apparaissent **en orange**. Pour chaque action notée :

- quel **message** (`CC`, la commande) change ;
- quel **octet** (`D0` = premier octet de données) et quel **bit** (bit 0 = poids faible) ;
- pour une valeur (vitesse, angle, température) : sur combien d'octets, dans quel ordre (gros-boutiste ou
  petit-boutiste), signée ou non, et la formule (`× 0,1`, `− 40`…).

## 3. Écrire la fiche

1. Copier [`template/new-car.json`](template/new-car.json) dans `brands/<marque>/<id>.json`. Le nom du fichier
   doit être son `id` : minuscules, chiffres, `-`. Par exemple `brands/peugeot/peugeot-308-raise.json`.
2. Remplir `name`, `description` (boîtier, protocole, d'où vient le décodage, essayée ou non), `box` et `baud`.
3. Lister les voitures dans `variants` : `"Marque Modèle 2015-2020, all trims"`.
4. Pour chaque message repéré, ajouter ses signaux sous `messages`, avec pour chacun un **rôle** : le nom commun de la
   valeur (`vehicle.speed`, `door.front_left`, `steering.angle`…). Liste des rôles :
   [`CanRoles.kt`](https://github.com/LibreHU/LibreHU-service/blob/main/core/src/main/kotlin/org/librehu/core/can/CanRoles.kt),
   alignée sur la COVESA Vehicle Signal Specification. Une valeur sans rôle connu : `x.<nom>`.
5. Les **touches du volant** dans `wheel_keys` (message, octet du code, octet d'état, codes « appuyé »).
6. Si le boîtier attend des messages de l'autoradio (type de voiture, bonjour…), les mettre dans `link.send`.
7. Mettre `"engine"` au moteur dont la fiche a besoin. L'outil vous le dit : `>=2.0` pour une fiche simple, `>=2.1` avec
   des formules (`expr`).

Un éditeur comme VS Code vérifie la fiche pendant la saisie, grâce à la ligne `$schema` du modèle.

## 4. Tester

1. Ajouter des **`examples`** : un message réel (copié de votre export) et les valeurs qu'il doit donner. Ce sont les
   auto-tests de la fiche ; ils garantissent qu'une future version du moteur la lira toujours pareil.
2. Sur l'ordinateur :

   ```bash
   java -jar librehu-car-tool.jar check brands/<marque>/<id>.json
   ```

   ```bash
   java -jar librehu-car-tool.jar decode brands/<marque>/<id>.json mon-export.txt
   ```

3. Sur l'autoradio : onglet CAN → **Importer** la fiche, choisir sa voiture, vérifier les valeurs et les touches.

## 5. Partager

- **Pull request** sur ce dépôt avec la fiche, de préférence avec un extrait d'export. **Retirez du fichier
  d'export** ce qui ne doit pas être public : le VIN et toute position GPS.
- Ou un **ticket « Nouvelle voiture »** (formulaire) si vous ne voulez pas écrire la fiche vous-même.
- La CI vérifie la fiche (schéma, auto-tests avec le vrai moteur, version du moteur), puis reconstruit le **paquet de
  la marque** : LibreHU Apps le propose aux autoradios dont le service sait le lire, sans mise à jour du service.

## Brouillons tirés de l'appli Car Info (outil en cours)

`tools/carinfo/` lit le listage jadx « fallback » de l'appli Car Info d'origine (jamais exécutée) et rejoue son code
dans un petit interpréteur pour savoir ce que fait chaque décodeur : quel décodeur pour quelle voiture, quels messages,
quels octets, quelle formule. Mode d'emploi : [tools/carinfo/README.md](tools/carinfo/README.md).

- État au 06/11/2026 : un décodeur trouvé pour 6 658 des 6 970 entrées du catalogue (532 décodeurs) ; mêmes résultats
  que les analyses à la main pour PSA (111 / 111) et Volkswagen (174 / 174) ; pour `RePsaProtocol`, mêmes messages que
  la fiche `psa-raise`.
- Pas encore fait : l'écriture des fiches (famille de boîtier ou `framing`, rôles, noms des touches, type de voiture,
  accusés, trames de démarrage) et leur vérification par le moteur (`librehu-car-tool.jar check`).
- Une fiche tirée de ce code n'a jamais roulé : elle sera marquée **non testée** tant que personne ne l'a essayée sur
  la voiture (comme toute fiche, à vérifier avec une capture, § 1).

## Règles

- Une fiche = un protocole de boîtier (souvent plusieurs voitures dans `variants`).
- Ne rien envoyer à la voiture qui ne soit pas compris : une commande (`link.commands`) doit venir d'une capture de
  l'appli d'origine du boîtier ou de sa documentation.
- Décodage repris d'une appli d'origine : écrire d'où il vient dans `description`. Ne pas recopier de code.
