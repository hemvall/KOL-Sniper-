# Plan de scale

## Niveau 1 — une clé, une instance active (implémenté)

- Handler Telegram concurrent et opérations réseau/SQLite hors de la boucle async.
- Sessions HTTP persistantes par thread, builder Node persistant, SQLite WAL.
- Déduplication et réservations d'ordres durables.
- Fan-out RPC avec transaction signée unique.
- Retour dès la première route RPC acceptée, sans attendre les routes lentes.
- Un seul WebSocket de prix partagé entre toutes les positions.
- Cache préchauffé du SDK et blockhash rafraîchi en arrière-plan.
- Récupération des ordres soumis et des positions ouvertes.
- Limites strictes et métriques de latence/erreur.

Ce niveau suffit largement au débit réaliste d'un portefeuille unique. Sur Solana, le goulot est le build/RPC/landing et la liquidité, pas le parsing Telegram.

## Niveau 2 — disponibilité sans double exécution

Avant une seconde instance active :

- PostgreSQL pour les opportunités, réservations, ordres et positions.
- Verrou distribué/leader unique par portefeuille.
- File durable avec clé d'idempotence `(source, message_id, mint)`.
- Secret manager/KMS ou service de signature isolé.
- OpenTelemetry + Prometheus/Grafana et alerting.

Une instance standby peut être déployée dès maintenant, mais elle ne doit pas écouter/trader simultanément avec la même clé.

## Niveau 3 — plusieurs portefeuilles/régions

- Partitionnement strict par portefeuille : un leader et un budget de risque par partition.
- Collecteurs Telegram proches de la source, horodatage monotone, bus régional.
- Builders/RPC préchauffés dans la région Solana la plus rapide mesurée.
- Routage adaptatif fondé sur taux de landing, p50/p95 et coût — pas seulement le ping.
- Réconciliation centrale des fills et comptabilité immutable.

## Critères avant scale financier

- 100–300 trades minimum avec coût total réel.
- Espérance nette et profit factor positifs hors échantillon.
- Drawdown compatible avec le capital.
- Aucune transaction non inspectée, aucun ordre ambigu resoumis.
- Tests chaos : RPC lent, websocket coupé, crash après submit, DB verrouillée, token gradué.

Le scale technique sans preuve d'espérance augmente surtout la vitesse des pertes.
