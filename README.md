# LibreHU car profiles

Fiches de voitures pour [LibreHU service](https://github.com/LibreHU/LibreHU-service) : comment parler au boîtier CAN
de chaque voiture et lire ses valeurs (touches du volant, portes, vitesse, moteur, clim, radar…). Une fiche par
protocole de boîtier, **un paquet par marque**, plus les **types de boîtiers** : téléchargés par le service lui-même
(onglet CAN) ou par LibreHU Apps, sans mettre à jour le service. Depuis le service v184, **aucune voiture n'est
intégrée au service** : elles viennent toutes d'ici.

*Car profiles for LibreHU service: how to talk to each car's CAN box and read its values. One pack per make, plus the
box types, downloaded by the service itself (CAN tab) or by LibreHU Apps, without updating the service; since service
v184 no car is built into it. Guide to port a car (French): [PORTING.md](PORTING.md).*

| Dossier | Contenu |
|---|---|
| `brands/<marque>/` | les fiches de la marque (`<id>.json`) |
| `boxes/` | **types de boîtiers** : le profil générique de chacun (`"box_type"` + sa `"framing"`, moteur 2.6 ; messages bruts, aucun décodage), paquet `boxes`. **Un nouveau boîtier = un fichier ici**, sans nouveau service ; une fiche le nomme par son `"box"` (ou par un de ses fabricants, `"aliases"`). Le service a les cinq actuels intégrés, en repli |
| `template/new-car.json` | fiche modèle à copier |
| `schema/` | schéma JSON du format (copie de celui du service) |
| `dist/` | **généré par la CI** : `index.json`, un paquet par marque (`<marque>.json`) et celui des types de boîtiers (`boxes.json`, installé avant les marques) |
| `tools/build_packs.py` | vérification par le schéma et construction des paquets |
| `tools/carinfo/` | **outil en cours** : rejoue les décodeurs de l'appli Car Info d'origine, à partir de son listage jadx « fallback » (l'appli n'est jamais exécutée), pour en tirer des brouillons de fiches ; voir [tools/carinfo/README.md](tools/carinfo/README.md) |

- **Porter une voiture** : [PORTING.md](PORTING.md).
- **Format** : [docs/can-vehicles.md](https://github.com/LibreHU/LibreHU-service/blob/main/docs/can-vehicles.md),
  page [Moteur voiture](https://librehu.github.io/engine.html).
- **Versions** : chaque fiche dit le moteur dont elle a besoin (`"engine": ">=2.1"`, Semantic Versioning) ; un paquet
  demande le plus récent de ses fiches ; le service et LibreHU Apps ne proposent que les paquets que votre service sait
  lire.
- **Intégrité** : chaque paquet est publié avec sa taille et son SHA-256 dans `dist/index.json` et dans
  `dist/SHA256SUMS` (à la main : `cd dist && sha256sum -c SHA256SUMS`), téléchargé en HTTPS ;
  le service (ou LibreHU Apps) vérifie l'empreinte et le service relit le paquet tout ou rien (pas de signature, choix du
  projet).
- **CI** : à chaque push et pull request, chaque jour, ou à la main (Actions → « Check and build packs » → Run workflow).
- **Révision d'un paquet** : nombre de commits qui ont touché son dossier ; corriger une Renault ne change que le
  paquet `renault`.
- **Voitures décodées** : <https://librehu.github.io/docs.html#can-cars>.


## Licence

Copyright (C) 2026 les contributeurs de LibreHU.

Les outils de ce dépôt (`tools/`) et le schéma (`schema/`, copie de celui de LibreHU-service) sont sous **GNU AGPL v3 ou ultérieure** (`AGPL-3.0-or-later`, fichier [`LICENSE`](LICENSE)), avec les
[termes additionnels](LICENSE-ADDITIONAL-TERMS.md) de son article 7 : garder la mention « Basé sur LibreHU –
https://github.com/LibreHU » et marquer une version modifiée comme telle. Qui distribue une version modifiée, ou la
fait utiliser à distance, doit en donner le code source complet sous la même licence.

Les **fiches** (`brands/`, `template/`) et les **paquets** (`dist/`) sont sous **CC BY-SA 4.0**
([`LICENSES/CC-BY-SA-4.0.txt`](LICENSES/CC-BY-SA-4.0.txt)) : les citer (« LibreHU car profiles –
https://github.com/LibreHU/LibreHU-car-profiles ») et partager une fiche modifiée sous la même licence.
Les décodages repris de l'appli d'origine d'un boîtier sont des relevés de comportement (aucun code copié), notés
dans la `description` de chaque fiche.

## Contact

[librehu@proton.me](mailto:librehu@proton.me)
