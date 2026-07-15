# Plan de scaling — KOL-Sniper à 2+ SOL par call, premier dans la file

> **Objectif énoncé** : monter la taille à > 2 SOL par call, passer devant les autres
> bots la plupart du temps (« first in the queue ») et rester net profitable.
>
> **Cadre** : « frontrun » ici = réagir à une information **publique** (le post du KOL,
> ou son achat on-chain visible de tous) plus vite que les autres. C'est une course de
> latence, pas du sandwiching de victime — le mempool Jito est d'ailleurs fermé depuis
> mars 2024, il n'existe plus de front-running mempool public sur Solana. Ce plan
> n'en construit pas.

État de l'art vérifié en **juillet 2026** (recherche multi-sources + passe de
fact-checking ; les points non re-vérifiés sont marqués ⚠️). Chiffres de latence et
prix : ordres de grandeur à re-mesurer, l'écosystème bouge tous les trimestres.

---

## 0. TL;DR — les trois décisions qui comptent

1. **Le goulot n° 1 n'est pas le RPC, c'est la réception du signal.** Sur un canal
   Telegram à fort trafic, un userbot Telethon passif reçoit le message avec
   **20 à 45 s de retard** (fan-out Telegram déprioritisé) — pendant que Bloom/Maestro
   snipent en ~0,15 s après réception. Deux parades : optimiser agressivement la
   réception Telegram (§2.2) et, surtout, **surveiller le wallet du KOL on-chain** :
   il achète *avant* de poster, donc un stream gRPC sur son wallet donne le signal
   10 s à plusieurs minutes avant même que le post existe (§2.1). C'est le seul
   moyen d'être structurellement « premier » — tout le reste ne fait que réduire
   l'écart avec les bots commerciaux.
2. **Le chemin d'envoi actuel est le pire possible.** RPC public gratuit + double
   aller-retour HTTP PumpPortal + fee statique ≈ 2-6 s signal→landed et des échecs
   en congestion. Cible : build local de la tx + Helius Sender (Amsterdam) + tips
   dynamiques ≈ 0,4-0,8 s, same-slot atteignable. (§3-§4)
3. **À 2+ SOL, la survie se joue hors latence.** Sur une curve fraîche, 2 SOL
   d'entrée coûtent ~6,7 % d'impact moyen + 1,25 % de frais : il faut ~x1,17 juste
   pour le break-even. Sans filtres pré-achat, exits disciplinés, sizing par KOL et
   kill-switch, être premier signifie seulement perdre plus vite. (§5-§8)

**Ne pas commencer par monter `BUY_SOL`.** Monter la taille est la dernière étape,
une fois la machine prouvée sur petite taille (§11).

---

## 1. Réalité du jeu (à lire avant de monter la taille)

Données 2024-2026, sources académiques et industrie :

- Le pic de prix post-call arrive en **0,12 à 1,49 minute**, puis effondrement.
  Les insiders vendent *pendant* que les followers achètent encore (arxiv 2412.18848,
  2105.00733). La fenêtre de profit d'un copy-trade de call se compte en secondes.
- Wallets KOL Solana (étude 1,6 M trades, 1 058 wallets) : win rate médian **57 %**,
  achat moyen 1,52 SOL mais **vente moyenne 2,24 SOL** — ils distribuent plus gros
  qu'ils n'accumulent. ~9 400 événements d'entrées coordonnées multi-KOL par
  fenêtre de 30 jours (5,1 KOL par cluster) : un call qui arrive *après* un cluster
  d'achats KOL est très probablement votre exit liquidity.
- Base rates pump.fun : ~69 % des tokens font leur dernier trade le jour de leur
  création ; taux de graduation tombé à **~0,26 % en 2026** ⚠️ ; ~98,6 % des launches
  ont un comportement rug-like (Solidus Labs). Sur les tokens « performants »,
  82,8 % montrent une croissance artificielle et les bundles au launch sont fréquents
  (arxiv 2507.01963).
- **Conséquence EV** : les pertes vont à -35/-90 %, les gains dépendent de votre
  vitesse de sortie. L'espérance vient de (a) la qualité du KOL, (b) la latence
  d'entrée ET de sortie, (c) la discipline de sizing. La latence seule ne rend pas
  la stratégie rentable — elle rend rentable une stratégie déjà saine.

---

## 2. Étape A — Gagner la course au signal (le plus gros gain)

### 2.1 Prio absolue : copier le wallet du KOL, pas son post

Le KOL achète on-chain **avant** de poster (pattern documenté : « buy before they
post, sell into the demand »). Toute personne qui lit le post — vous inclus — est en
retard par construction. Le contournement :

1. **Identifier le(s) wallet(s) d'achat du KOL** :
   - Outils gratuits : **kolscan.io** (mapping Twitter→wallet + PnL, racheté par
     pump.fun), labels KOL/smart-money **GMGN**, **Arkham** (Solana supporté),
     **MadeOnSol** (1000+ wallets KOL), **Cielo** (free : 10 wallets Solana suivis ;
     Pro ~59 $/mois : 200 wallets).
   - Pour les wallets annexes non labellisés (fréquents) : prendre 3-5 calls passés
     du KOL, extraire les acheteurs des 0-10 min précédant chaque post
     (Solscan/GMGN), **intersecter les ensembles** — le wallet récurrent est le bon.
     Re-vérifier en continu : les KOL font tourner leurs wallets. C'est le vrai
     travail difficile de cette approche.
2. **Streamer ce wallet en temps réel** via Yellowstone gRPC :
   `transactionsSubscribe { accountInclude: [WALLET], commitment: processed }`,
   parser les interactions avec le programme pump.fun
   (`6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`) pour extraire le mint, déclencher
   l'achat. Détection ~100-300 ms après l'inclusion de la tx du KOL.
3. **Fournisseurs gRPC** (juillet 2026) :
   - Helius **LaserStream** : inclus au plan Business 499 $/mois (10 connexions,
     9 régions dont AMS/FRA, ~5-15 ms de latence slot annoncée).
   - Moins cher, flat : **AllenHark** ~99 $/mois, **Shyft** ~199 $/mois,
     **SolanaTracker** ~200 €/mois (enrichi Jito Shreds, ~50-100 ms plus rapide).
   - **Jito ShredStream** : gratuit sur approbation (keypair whitelistée), régions
     AMS/FRA incluses — mais décodage de shreds non trivial (3-7 j de dev) ; à garder
     pour plus tard.
   - Bande passante filtrée sur quelques wallets : quelques GB/mois, négligeable.

**Impact** : signal 10 s à plusieurs minutes avant tous les bots qui lisent le canal.
C'est le seul levier qui vous met devant Bloom/Maestro/Trojan, qui subissent le même
fan-out Telegram que vous.

**Risque assumé** : si le KOL utilise un wallet frais jamais vu, vous retombez sur le
fallback Telegram. Les deux pipelines coexistent (dédup par mint, déjà en place via
`bought`).

### 2.2 Fallback Telegram : tuer le délai de fan-out

Confirmé par les issues Telethon (#3150, #652) : un compte passif sur un gros canal
reçoit le message avec 20-45 s de retard ; un compte qui « consulte » le canal tombe
à 1-5 s. Actions, par ordre d'impact :

- **Compte(s) dédié(s) propre(s)** : numéro européen (→ home DC Amsterdam, DC2/DC4),
  abonné **uniquement** aux canaux cibles, éventuellement Premium ⚠️ (effet plausible,
  non prouvé). Le compte actuel, s'il suit des dizaines de canaux, est déprioritisé.
- **3-5 comptes/sessions Telethon en parallèle**, on garde le premier
  `UpdateNewChannelMessage` reçu (dédup par message id). L'ordre de fan-out par
  abonné est quasi aléatoire : la course en parallèle écrase la queue de latence.
- **Poller actif ~1 Hz** en filet : `GetHistoryRequest`/`GetChannelDifference` sur le
  canal cible (sous les flood-limits). C'est ce qui reproduit l'effet « canal ouvert
  sur mobile » qui fait passer de 20-45 s à 1-5 s.
- **Hot path minimal** : handler sur l'update brute (pas de résolution d'entités
  dans le chemin chaud), regex précompilées (déjà le cas), `cryptg` installé,
  connexion persistante avec pings. Pas de `catch_up` (inutile en live).
- **Héberger à Amsterdam** : RTT 1-3 ms vers les DC Telegram européens (§9).
- ⚠️ Note de maintenance : le repo Telethon est archivé depuis février 2026 —
  épingler la version, prévoir à terme une alternative MTProto maintenue.

**Anti-recommandations** (vérifiées) : Bot API (couche HTTP plus lente et un bot ne
lit pas un canal sans y être admin) ; `catch_up=True` ; monter le priority fee
statique sans changer le chemin d'envoi ; utiliser Cielo/alertes TG comme signal
d'*exécution* (bien pour la découverte de wallets, trop lent pour trader).

---

## 3. Étape B — Construire la transaction localement (supprimer PumpPortal du hot path)

Le POST vers `pumpportal.fun/api/trade-local` coûte **50-300 ms** de RTT HTTPS
(serveurs US-centric) **+ 0,5 % de frais par trade** (0,01 SOL par trade de 2 SOL),
avant même de signer. À remplacer par une construction 100 % locale :

- **Programme pump.fun** : `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P` ;
  global PDA `4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf` ;
  `bonding_curve` = PDA `["bonding-curve", mint]` ; fee program
  `pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ`. Instructions : `buy` legacy
  (18 comptes depuis l'upgrade du 2026-04-28) ou `buy_exact_quote_in_v2`
  (2026-05-21, 27 comptes — on fixe le SOL exact dépensé, idéal pour sniper).
  Attention aux coins quotés USDC (v2 obligatoire) : détecter le quote mint.
- **Pré-calculer tout ce qui est statique au démarrage** (global, fee_config,
  event_authority, volume accumulators, les 8 fee_recipients — en tirer un au hasard
  par tx, reco officielle) ; dériver par mint en <1 ms (bonding_curve, ATAs, ATA user
  créée via `createAssociatedTokenAccountIdempotent` dans la même tx). Sur curve
  fraîche, **ne pas lire l'état on-chain** : utiliser les constantes initiales.
- **Blockhash pré-fetché en continu** (tâche de fond, refresh à chaque slot) — jamais
  de `getLatestBlockhash` dans le chemin chaud.
- **Librairies de référence maintenues** (vérifié juillet 2026) :
  Python `chainstacklabs/pumpfun-bonkfun-bot` (Apache-2.0, à jour de l'upgrade
  2026-04-28, pump.fun + letsbonk) ; Rust `pump-rust-client` (v0.1.8, 2026-06-15) ;
  TS officiels `@pump-fun/pump-sdk@1.36` / `@pump-fun/pump-swap-sdk@1.18`.
  **Ne pas utiliser** le crate Rust `pumpfun` 4.6.0 (plus mis à jour depuis
  oct. 2025, antérieur au break d'avril 2026).
- **Vendorer les IDL et surveiller `t.me/pump_tech_updates`** : pump.fun a cassé le
  format des comptes 3 fois en 12 mois (fév. 2026 cashback/`bonding_curve_v2`,
  avr. 2026 +1 compte/8 fee recipients, mai 2026 v2/USDC). Chaque break = 100 % de
  trades ratés jusqu'au fix — être à jour le jour J est en soi un edge.
- **Routage par venue** : suffixe `pump` → bonding curve ; si `complete=true` →
  PumpSwap (`pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA`) ; `bonk` → Raydium
  LaunchLab (`LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj`) ; `moon` → Moonit.
  Stratégie pragmatique : build local pour pump.fun (l'énorme majorité des calls),
  **garder PumpPortal en fallback** pour les autres venues et comme chemin B si le
  pipeline local casse (Lightning : 1 %/trade, clé custodiale — secours uniquement).
- **Slippage 30-50 %, pas 10-15 %** : le slippage s'applique via `max_sol_cost`
  (plafond, pas coût réel). En course, chaque SOL concurrent qui atterrit avant vous
  sur une curve fraîche déplace le prix de ~3,3 % ; à 15 % vous enchaînez les
  `TooMuchSolRequired` dès ~2 SOL de flux devant vous. Le plafond borne la perte,
  la curve détermine le prix payé.

**Gain** : -50 à -300 ms déterministes + 0,5 % de frais économisés par trade.

---

## 4. Étape C — Faire atterrir la tx en premier

### 4.1 Chemin principal : Helius Sender (vérifié)

- Endpoints régionaux `http://{ams,fra,…}-sender.helius-rpc.com/fast` — dispo dès le
  plan **gratuit**, 0 crédit API, ~50 TPS par défaut.
- Une seule tx signée : instruction de **tip ≥ 0,001 SOL** vers un des 10 tip
  accounts Helius + `setComputeUnitPrice` obligatoire ; `skipPreflight=true`,
  `maxRetries=0` (re-send manuel à chaque slot jusqu'à confirmation).
- Fan-out natif simultané **SWQoS + Jito + Harmonic + Rakurai** : le double-routage
  sans risque de double-achat. Mode `swqos_only=true` (tip 0,000005 SOL) pour les
  trades non critiques. Garder la connexion chaude via `/ping` toutes les 30-60 s.

### 4.2 Redondance : Jito direct + Nozomi (optionnel, palier sérieux)

- **Jito `sendTransaction`** (`https://ams/frankfurt….block-engine.jito.wtf/api/v1/transactions`) :
  min tip 1000 lamports, `bundleOnly=true` = revert protection, 1 req/s/IP sans clé.
- **Nozomi/Temporal** (`ams1/fra2.nozomi.temporal.xyz/?c=KEY`) : tip min 0,001 SOL
  **payé uniquement si la tx atterrit**, CU price ≥ 1M micro-lamports recommandé,
  accès sur candidature.
- **Règle absolue du multi-routage** : une **seule** tx signée contenant les
  instructions de tip des deux providers, envoyée partout en parallèle. Jamais deux
  variantes signées différemment — les deux peuvent atterrir = double achat.
- Alternatives premium si scaling : **0slot** (SWQoS dédié, 5/20/50 TPS, essai 1
  semaine), **bloXroute Trader API**, **BlockRazor** (sendTransaction gratuit ~3 TPS,
  tip flat min 0,0001 SOL ; streams payants à part). Utile au-delà de ~20 trades/jour.

### 4.3 Tips et priority fees dynamiques (jamais statiques)

- **Tip Jito** : s'abonner à `wss://bundles.jito.wtf/api/v1/bundles/tip_stream` (ou
  GET `tip_floor`). **Ne jamais hardcoder** : le p99 varie de x30+ dans la même
  journée (mesuré : 0,0002 vs 0,0077 SOL à quelques heures d'écart le 15/07/2026).
  Politique : tip = max(p95 live × 2, 0,001 SOL), plafonné à ~0,5 % du trade
  (0,01 SOL pour 2 SOL). Les races de snipe se gagnent entre p95 et p99.
- **Priority fee** : Helius `getPriorityFeeEstimate` sur la tx sérialisée, niveau
  `veryHigh` (~p95). Reco Jito : ~70 % priority fee / 30 % tip.
- À 2+ SOL/trade, passer le tip de 0,001 à 0,005-0,01 SOL coûte 0,25-0,5 % du trade :
  c'est le levier de priorité intra-slot le moins cher une fois la latence payée.

### 4.4 Se protéger soi-même du MEV

Le sandwiching n'a pas disparu, il a migré vers des **mempools privés de
validateurs** (rapport MEV Helius : une seule entité ≈ 50 % des sandwiches). Un achat
de 2 SOL avec 30-50 % de slippage est une cible parfaite. Parades : ne router que
par des senders de confiance (Sender `mev-protect`, Jito `bundleOnly`,
`jitodontfront`), et ne jamais envoyer au RPC public une tx à gros slippage.

### 4.5 Budget latence cible

| Étape | Actuel (estimé) | Cible palier a | Cible palier b/c |
|---|---|---|---|
| Signal (post→bot) | 1-45 s (Telethon passif) | 0,3-2 s (TG optimisé) | **-10 s à -120 s** (wallet gRPC : avant le post) |
| Build tx | 100-300 ms (PumpPortal) | <5 ms (local) | <5 ms |
| Envoi→landed | 0,8-4 s + échecs (RPC public) | 0,4-0,8 s (Sender, 1-2 slots) | 0,4 s (same-slot possible) |
| **Total** | **2-6 s après le post** | **~0,7-2,8 s après le post** | **avant le post** |

---

## 5. Étape D — Ce que 2+ SOL change : la géométrie de la curve

Produit constant sur réserves virtuelles ; constantes vérifiées (pump-public-docs) :
30 SOL virtuels / 1 073 000 191 tokens virtuels initiaux, migration à ~85 SOL réels
levés, frais bonding curve **1,25 %** (0,95 % protocole + 0,30 % créateur ou
cashback). Pour un achat de S SOL : prime moyenne vs spot = S/x ; prix post-achat =
spot × (1+S/x)².

**Curve fraîche (x = 30)** :

| Taille | Premium moyen payé | Prix après votre achat |
|---|---|---|
| 0,5 SOL | +1,7 % | +3,4 % |
| 1 SOL | +3,3 % | +6,8 % |
| **2 SOL** | **+6,7 %** | **+13,8 %** |
| 3 SOL | +10,0 % | +21,0 % |
| 5 SOL | +16,7 % | +36,1 % |

**Curve à ~50 % des tokens réels vendus (x ≈ 47,6)** : 2 SOL → +4,2 % / +8,6 % ;
5 SOL → +10,5 % / +22,1 %.

Conséquences pratiques :

- **Coût total d'entrée à 2 SOL sur curve fraîche ≈ 8 %** (impact + 1,25 % de frais).
  Break-even aller-retour (frais retour + impact de votre propre vente inclus) :
  le spot doit faire **~x1,17**. À 5 SOL : ~x1,39. La taille est son propre ennemi.
- **Cap de liquidité** : position ≤ ~5 % des réserves SOL réelles de la curve au
  moment de l'achat, sinon votre propre sortie coûte >10 %. Une curve fraîche ne
  peut pas absorber 2 SOL proprement — soit entrer plus tard sur la curve, soit
  réduire la taille, soit splitter.
- **Split d'entrée** : première tranche sonde (ex. 0,5 SOL) + solde si le fill est
  sain (prix reçu vs attendu). Réduit l'entrée moyenne ET sert de probe de
  sellabilité pour les venues hors pump.fun.
- **Entry cap** : skip si l'impact projeté pour votre taille dépasse un seuil
  (configurable, ex. 8 %) — la curve est trop fine pour votre ticket.
- **Comptabilité réelle** : logger l'entrée moyenne *réalisée* depuis la tx
  confirmée (tokens reçus / SOL dépensés), pas `BUY_SOL`.

---

## 6. Étape E — Filtres pré-achat (obligatoires à cette taille)

Budget : **~300 ms, en parallèle du build** — abort de l'envoi si échec. Une seule
entrée toxique à 2 SOL efface 5-10 trades gagnants.

**Étage 0 — gratuit, local, instantané** (branchement par venue) :
- Mint pump.fun natif (suffixe `pump`, curve active) : mint/freeze authority et LP
  sont sûrs **par construction** (vérifié : authorities null, SOL séquestré dans la
  curve, `withdraw` désactivée). Le honeypot classique est impossible — ne pas
  gaspiller de latence à le tester. Les risques restants : dev dump, supply bundlée,
  distribution.
- Token **hors** pump.fun : check complet obligatoire — rejeter si owner =
  Token-2022 (vecteurs actifs : DefaultAccountState=frozen, Permanent Delegate,
  Transfer Hook, Transfer Fee), si freeze/mint authority non null, si LP Raydium
  legacy non burn/lock. Sinon taille réduite ou skip.

**Étage 1 — on-chain, ~60-100 ms, bloquant** : un seul `getMultipleAccounts`
(mint, bonding curve PDA, ATA créateur) + `getTokenLargestAccounts` (top-20 holders,
exclure le compte de la curve). Rejets hard-codés (seuils à calibrer en backtest) :
- dev/créateur > 5-10 % de la supply ;
- top-10 holders (hors curve) > 25-30 % ;
- bundle au launch > ~15 % de supply (les tokens manipulés montrent en moyenne
  15,7 % de supply bundlée) ;
- curve `complete` ou réserves incohérentes avec le calcul d'impact.

**Étage 2 — indexeur, timeout 250 ms, parallèle** : SolanaTracker risk score
(1-10, snipers/insiders/bundlers ; Free 10k req/mois puis 50 €/mois) ou GMGN
`/v1/token/security`. Timeout → acheter à taille réduite sur la base de l'étage 1,
ou skip (configurable).

**Post-fill, asynchrone** : RugCheck `/v1/tokens/{mint}/report/summary` (gratuit ;
la régénération forcée existe avec clé payante via `?refresh`) — si score critique,
sortir immédiatement au lieu de dérouler le ladder. Trop lent/inconstant sur mints
très frais pour le chemin critique.

**Filtre anti-exit-liquidity** : vérifier via l'indexeur si des wallets KOL connus
sont déjà positionnés sur le token avant votre achat. Un call qui arrive après un
cluster d'achats KOL coordonnés = distribution en cours → skip ou taille minimale.

---

## 7. Étape F — Sorties (là où le PnL se fait réellement)

Le `monitor_and_sell` actuel (un websocket, TP/SL binaire, vente par le chemin lent)
est insuffisant. Cibles, calibrées sur une demi-vie de pump de 1-2 minutes :

- **Le sell prend le MÊME chemin rapide que le buy.** Tx de sell pré-construite au
  moment du fill (blockhash rafraîchi ~30 s), slippage d'urgence 25-50 %, envoi
  Sender/Jito. Un bot qui entre en 1 slot et sort en 10 slots stop-loss dans le vide.
- **Ladder** : TP1 = vendre 50 % à **+40-80 %** (ne pas attendre x2 — récupère
  presque le principal, transforme la distribution du trade) ; TP2 = 25 % à x2 ;
  solde en **trailing stop 30-50 %** du plus-haut ; stop initial -35/-50 % remonté à
  break-even après TP1 ; **time-stop** : sortie totale si aucun nouveau plus-haut en
  60-120 s (un call mort bleed par le spread et l'opportunité).
- **Trigger de dump temps réel** (réutilise le stream gRPC de §2.1, pointé sur la
  curve) : auto-sell immédiat si le créateur ou un top-5 holder vend >50 % de sa
  position, si une vente unique retire >5-10 % des réserves SOL, ou si 3+ ventes
  >1 SOL tombent dans le même slot. Transforme un -60/-90 % (dev dump) en -15/-30 %.
  C'est le filet n° 1 pour des tailles > 2 SOL.
- **Monitoring résilient** : reconnexion automatique du feed de prix + source de
  secours ; si le feed meurt > N secondes avec position ouverte → sortie de sécurité.

---

## 8. Étape G — Sizing et gestion du risque

- **Quarter-Kelly** : estimer p/W/L **par KOL** depuis `calls.csv` enrichi ;
  f* ≈ (pW − qL)/(W·L), miser 10-25 % de f*. Exemple réaliste (p=0,45, W=+60 %,
  L=-35 %) → ~8-10 % du bankroll par trade → **2 SOL/trade exige un bankroll dédié
  de 20-25 SOL minimum**. À 10 SOL de bankroll, 2 SOL/trade est une quasi-certitude
  de ruine sur ce style de distribution.
- **Caps** : max 2-3 positions simultanées ; cap d'exposition totale ; cap par KOL ;
  position ≤ 5 % des réserves SOL de la curve (§5) ; buffer SOL réservé aux
  frais/tips pour ne jamais rater une *sortie* faute de gas.
- **Kill-switch** (redémarrage manuel uniquement) : halt à -10/-15 % du bankroll
  journalier OU 3-5 pertes consécutives OU >20 % de tx non-landées sur 10 trades OU
  latence de fill > 2× la médiane (infra dégradée = fills tardifs = achats au top).
  Mode demi-taille dès -5 % journalier.
- **La variable qui domine tout : l'EV par KOL.** Logger pour chaque call le prix à
  +5 s/+30 s/+2 min/+10 min, votre latence effective, le slippage réalisé, le PnL.
  Purge hebdomadaire des KOL à EV négative après frais. La même infra est rentable
  sur un KOL « early » et structurellement perdante sur un distributeur — aucun
  réglage de latence ne compense un mauvais KOL.

---

## 9. Infrastructure et coûts

**Localisation : Amsterdam** (choix unique optimal) — DC Telegram DC2/DC4 sur place,
Jito block engine AMS, Helius Sender AMS, Nozomi ams1, 0slot ams ; Francfort à
~5-8 ms en second envoi (≈30 % des validateurs). Un serveur US perd 40-90 ms rien
que sur la réception Telegram. ⚠️ (axe infra non re-vérifié par la passe de
fact-checking, mais recoupé par les axes landing/signal qui l'ont été.)

- **Serveur** : le bot est léger (2-4 vCPU / 4-8 GB). Vultr High Performance AMS
  ~12-24 $/mois pour commencer ; Latitude.sh bare metal (~296 $/mois, orienté
  Solana, paiement crypto) au palier sérieux pour tuer le jitter p99.
  **Pas Hetzner** : ses System Policies interdisent explicitement le trading/crypto
  (précédent : >1000 validateurs Solana coupés en nov. 2022).
- **Langage** : Python n'est pas le goulot. `solders` (bindings Rust) build+sign en
  1-5 ms ; httpx/aiohttp persistant + uvloop suffisent pour un hot path <20 ms de
  code. Les gains sont architecturaux (round-trips supprimés, connexions chaudes,
  pré-calcul). Une réécriture Rust du chemin d'envoi ≈ 5-20 ms de mieux — moins
  qu'un tip supérieur ; à différer au palier c.

**Paliers de dépense** :

| Palier | Stack | Coût fixe | Ce que ça achète |
|---|---|---|---|
| a) Minimal | VPS AMS + Helius Developer 49 $ + Sender (gratuit) + build local + TG optimisé | ~60-75 $/mois + tips | Devant la majorité des bots amateurs ; landing 1-2 slots |
| b) Sérieux | + Helius Business 499 $ (LaserStream : wallet-copy §2.1 + trigger dump §7) ou gRPC flat (AllenHark/Shyft/SolanaTracker ~99-200 $) + bare metal | ~400-550 $/mois + tips | Signal avant le post ; same-slot atteignable ; sorties temps réel |
| c) Semi-pro | + 0slot/Nozomi payants, ShredStream, Rust send path, multi-région | >1000 $/mois + tips | >95 % de landing en congestion, priorité intra-slot systématique |

Coût variable : ~0,002-0,011 SOL de tips/frais par trade — négligeable (<0,5 %) à
2 SOL/trade. Le palier b n'a de sens qu'une fois le palier a **prouvé rentable**.

---

## 10. Mesurer (sinon on règle au feeling)

Instrumenter chaque trade dans `calls.csv`/SQLite :
- `t_signal` (réception, `time.monotonic_ns()` — `message.date` n'a qu'une précision
  d'une seconde, inutilisable), `t_built`, `t_sent`, `send_slot`, `landed_slot`,
  prix attendu vs réalisé, tip/fee payés, résultat.
- KPIs : **slot delta** (`landed_slot − send_slot`, cible 0-1), **landing rate**
  (cible >95 %), `t_sent − t_signal` (cible <30 ms), slippage réalisé, et l'écart
  entre votre prix d'entrée et le prix au moment du post (mesure votre place réelle
  dans la file).
- A/B tester les senders/tips sur données réelles, fenêtre 14h-18h UTC (congestion).
  Référence externe neutre : leaderboard.netticode.com ⚠️.

---

## 11. Ordre de déploiement (avec critères de passage)

Chaque étape a un **gate** mesurable ; on ne passe pas à la suivante sans le franchir.
La taille ne monte qu'à la fin.

1. **Instrumentation** (§10) sur le bot actuel, 2-3 jours de trades à 0,1-0,3 SOL.
   → Baseline chiffrée signal→landed.
2. **Chemin d'envoi** : build local (§3) + Helius Sender + tips dynamiques (§4) +
   VPS Amsterdam. *Gate : landing rate >90 %, slot delta ≤2, t_sent−t_signal <50 ms.*
3. **Signal** : Telegram optimisé multi-sessions (§2.2), puis wallet-copy gRPC (§2.1)
   sur 2-3 KOL bien identifiés. *Gate : entrée systématiquement avant le prix du
   post (mesuré), ou détection avant le post sur >50 % des calls en wallet-copy.*
4. **Sécurité + exits** : filtres (§6), ladder + trigger dump + sell rapide (§7),
   guardrails (§8). *Gate : 2 semaines à 0,3-0,5 SOL, EV nette positive après frais,
   kill-switch jamais contourné.*
5. **Scaling** : 0,5 → 1 → 2 SOL par paliers, sizing par KOL, en surveillant que le
   slippage réalisé et l'EV tiennent à chaque palier (l'impact §5 croît avec la
   taille — l'edge peut disparaître en montant). *Gate à chaque palier : EV/trade
   stable ou croissante sur ≥30 trades.*

---

## 12. Checklist concrète dans ce repo

Config (`.env`) :
- [ ] `SOL_RPC_URL` → Helius (lecture) ; nouveaux : `SENDER_URL_PRIMARY/SECONDARY`,
      `TIP_POLICY` (p95x2, min, cap), `PRIORITY_FEE_LEVEL=veryHigh`
- [ ] `BUY_SOL` → `BASE_BUY_SOL` + `MAX_BUY_SOL` + overrides par canal/KOL
- [ ] `SLIPPAGE` 15 → 30-50 ; `ENTRY_SLICES`, `PROBE_SOL`, `MAX_IMPACT_PCT`
- [ ] `MAX_CONCURRENT_POSITIONS`, `MAX_TOTAL_EXPOSURE_SOL`, `MAX_DAILY_LOSS_PCT`,
      `MAX_CONSECUTIVE_LOSSES`
- [ ] `GRPC_ENDPOINT`, `KOL_WALLETS` (liste), `SAFETY_TIMEOUT_MS=250`

Code :
- [ ] `sniper.py::_send` : supprimer PumpPortal du hot path ; module `tx_builder.py`
      (build local pump.fun, IDL vendorés, blockhash de fond, PDAs pré-calculées)
- [ ] Module `sender.py` : Sender/Jito/Nozomi, une-tx-multi-tips, re-send par slot,
      warm connections, tips dynamiques (tip_stream)
- [ ] Module `safety.py` : étages 0/1/2 (§6), en parallèle du build, abort si échec
- [ ] Module `signals/` : sessions Telethon multiples + dédup ; `wallet_watch.py`
      (gRPC transactionsSubscribe sur KOL_WALLETS)
- [ ] Réécrire `monitor_and_sell` : ladder + trailing + time-stop + trigger dump
      gRPC + sell pré-construite sur chemin rapide + reconnexion
- [ ] `logger.py` : colonnes latence/slots/slippage réalisé/prix à +5s/+30s/+2min/
      +10min ; stats par KOL ; kill-switch
- [ ] `requirements.txt` : corriger `solder` → `solders` (typo actuelle), ajouter
      `httpx`, `uvloop`, `cryptg`, client gRPC (`yellowstone-grpc` / `grpcio`)

Ops :
- [ ] VPS Amsterdam, process 24/7 (systemd), sessions Telegram chaudes
- [ ] Compte(s) Telegram dédiés propres (numéro EU) ; identification wallets KOL
- [ ] Abonnement `t.me/pump_tech_updates` (breaks de format pump.fun)
- [ ] Dashboard latence/landing (SQLite + script suffit au début)

---

## 13. Ce que ce plan ne promet pas

- **« Premier la plupart du temps » sur le post public** face aux bots commerciaux
  colocalisés n'est réaliste qu'avec le wallet-copy (§2.1) — sur le post lui-même,
  l'objectif atteignable est « dans le même slot que les meilleurs », pas devant.
- Être premier sur un mauvais call reste une perte rapide. La rentabilité vient du
  tri des KOL (§8) au moins autant que de la latence.
- Les chiffres (prix, endpoints, formats d'instruction) sont ceux de juillet 2026,
  vérifiés quand marqué, mais cet écosystème casse ses API plusieurs fois par an :
  re-vérifier avant chaque implémentation.
