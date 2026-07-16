# Bilan simple du projet KOL Sniper

## Verdict

Le projet a été fortement refait et sécurisé. Il est maintenant adapté à une **instance active par wallet**, avec un mode simulation activé par défaut.

La rentabilité n’est pas encore prouvée. Le code peut exécuter plus proprement et plus vite, mais il faut mesurer les résultats sur de vrais trades avant d’augmenter le capital.

## Ce qui est maintenant en place

- `DRY_RUN=true` par défaut : aucun achat accidentel.
- Achat et vente sur Pump.fun, y compris les tokens passés sur PumpSwap.
- Validation complète de chaque transaction avant signature.
- Limites de montant, exposition, positions, pertes et ordres en attente.
- Réconciliation automatique après timeout, erreur RPC ou redémarrage.
- Sorties persistantes : paliers, stop-loss, trailing stop et durée maximale.
- Une seule connexion de prix partagée entre les positions.
- Envoi simultané vers plusieurs RPC avec retour dès la première acceptation.
- Builder Pump isolé de la clé privée en production.
- Suivi du PnL, des frais, du profit factor et du drawdown depuis les fills confirmés.

## Validation effectuée

- 33 tests passent.
- Ruff et MyPy passent.
- Aucun problème Python connu avec `pip-audit`.
- Achats non signés testés sur bonding curve et PumpSwap.
- Vente PumpSwap non signée testée.
- Pipeline local autour de quelques millisecondes hors réseau.
- Objectif de 400–800 ms techniquement plausible, mais à mesurer sur le VPS réel.

## Important avant le live

1. Révoquer l’ancienne session Telegram : elle existe encore dans l’historique Git.
2. Purger `sniper_session.session` de l’historique avant de rendre le dépôt public.
3. Utiliser un wallet dédié avec très peu de SOL.
4. Commencer à `0.001–0.005 SOL` et une seule position.
5. Tester un achat et une vente bonding curve réels.
6. Vérifier chaque transaction sur un explorer Solana.
7. Mesurer la latence Telegram → acceptation RPC et le taux de landing.

Le SDK Pump officiel contient encore une dépendance signalée par `npm audit` (`bigint-buffer`). Elle est isolée du processus qui possède la clé privée, mais il faut surveiller les mises à jour upstream.

## Quand augmenter la taille ?

Pas avant d’avoir au moins 100 à 300 trades confirmés avec :

- frais et slippage inclus ;
- espérance nette positive ;
- profit factor positif et stable ;
- drawdown acceptable ;
- résultats également positifs hors échantillon.

Plusieurs instances ne doivent jamais trader simultanément avec le même wallet. Pour scaler horizontalement, il faudra PostgreSQL et un leader unique par wallet.

## Démarrage

```bash
cp .env.example .env
chmod 600 .env
.venv/bin/python sniper.py --check
.venv/bin/python sniper.py
```

Déploiement recommandé :

```bash
docker compose up --build -d
docker compose logs -f sniper
```

Consulter les résultats :

```bash
.venv/bin/python logger.py --json
```

Documentation détaillée : `README.md`, `SETUP.md`, `SECURITY.md` et `SCALING_PLAN1.md`.
