# Mise en production

## 1. Rotation de sécurité obligatoire

Le fichier `sniper_session.session` a été versionné dans l'historique Git. Le supprimer du dernier commit ne révoque pas sa clé d'autorisation Telegram.

1. Révoquer toutes les sessions Telegram inconnues/anciennes dans **Settings → Devices**.
2. Générer une nouvelle session après révocation.
3. Considérer toute clé privée ou tout token bot ayant partagé ce dépôt comme compromis et les remplacer.
4. Purger le fichier de tout l'historique Git avant de rendre le dépôt public (par exemple avec `git filter-repo`), puis forcer la rotation des clones. Cette opération réécrit l'historique et n'est pas faite automatiquement.

## 2. Installation

```bash
python3.12 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements-dev.lock
npm ci
cp .env.example .env
chmod 600 .env
umask 077
```

Après une modification volontaire des fichiers `requirements*.txt`, régénérer les deux locks hashés avec `pip-compile --generate-hashes` et les auditer avant déploiement.

Compléter `.env`. La clé privée accepte une clé base58 ou un tableau JSON de 64 octets. Ne jamais la mettre dans la ligne de commande, un commit, un log ou une image Docker.

## 3. Validation hors-ligne

```bash
.venv/bin/ruff check .
.venv/bin/mypy .
.venv/bin/pytest
npm run check:builder
.venv/bin/python sniper.py --check
.venv/bin/python -m tools.benchmark -n 100
```

Avec `DRY_RUN=true`, démarrer le listener et vérifier : signaux reconnus, déduplication, limites, `/health`, `/metrics` et redémarrage. Les endpoints de santé restent volontairement sur loopback ; utiliser un tunnel SSH pour les consulter à distance.

## 4. Validation live progressive

1. Utiliser un portefeuille dédié contenant seulement le capital nécessaire.
2. Commencer à `0.001–0.005 SOL` et une seule position.
3. Conserver `ALLOW_BUILDER_FALLBACK=false`.
4. Vérifier sur l'explorer chaque signature, fill, montant et programme.
5. Tester une vente partielle puis un redémarrage avec position ouverte.
6. Vérifier que `last_submit_latency_ms` mesure bien 400–800 ms ou moins dans la région choisie.
7. Augmenter très progressivement, jamais avant une série statistiquement exploitable.

Pour Helius Sender, configurer une URL et un compte de tip provenant de la documentation Helius à jour. Le service refuse Sender si la transaction ne contient pas à la fois priority fee et tip.

## 5. Exploitation

Docker :

```bash
docker compose up --build -d
docker compose logs -f sniper
```

Systemd : créer deux utilisateurs distincts (`sniper` et `sniper-builder`), rendre `/opt/kol-sniper/.env` lisible uniquement par root, et créer `/etc/kol-sniper-builder.env` avec **uniquement** `RPC_URL`. Adapter ensuite les chemins dans les deux unités :

```bash
sudo cp deploy/kol-sniper-builder.service /etc/systemd/system/
sudo cp deploy/kol-sniper.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now kol-sniper-builder kol-sniper
```

Alertes recommandées : absence de signal inattendue, ordre `unknown`, taux d'échec, latence p95, exposition, perte journalière, espace disque, solde SOL et fraîcheur du websocket.
