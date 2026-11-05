# LibreHU car profiles

Fiches de voitures pour [LibreHU service](https://github.com/LibreHU/LibreHU-service) : comment parler au boîtier CAN
de chaque voiture et lire ses valeurs (touches du volant, portes, vitesse, moteur, clim, radar…). Une fiche par
protocole de boîtier, **un paquet par marque**, mis à jour par LibreHU Apps sans mettre à jour le service.

*Car profiles for LibreHU service: how to talk to each car's CAN box and read its values. One pack per make, updated
by LibreHU Apps without updating the service. Guide to port a car (French): [PORTING.md](PORTING.md).*

| Dossier | Contenu |
|---|---|
| `brands/<marque>/` | les fiches de la marque (`<id>.json`) |
| `template/new-car.json` | fiche modèle à copier |
| `schema/` | schéma JSON du format (copie de celui du service) |
| `dist/` | **généré par la CI** : `index.json` et un paquet par marque (`<marque>.json`) |
| `tools/build_packs.py` | vérification par le schéma et construction des paquets |

- **Porter une voiture** : [PORTING.md](PORTING.md).
- **Format** : [docs/can-vehicles.md](https://github.com/LibreHU/LibreHU-service/blob/main/docs/can-vehicles.md),
  page [Moteur voiture](https://librehu.github.io/engine.html).
- **Versions** : chaque fiche dit le moteur dont elle a besoin (`"engine": ">=2.1"`, Semantic Versioning) ; un paquet
  demande le plus récent de ses fiches ; LibreHU Apps ne propose que les paquets que votre service sait lire.
- **Révision d'un paquet** : nombre de commits qui ont touché son dossier ; corriger une Renault ne change que le
  paquet `renault`.
- **Voitures décodées** : <https://librehu.github.io/docs.html#can-cars>.

Licence : GPL-2.0 (fichier `LICENSE`).
