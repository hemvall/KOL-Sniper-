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

## 0. TL;DR — recalé sur la réalité mesurée

**Baseline réelle (confirmée par l'utilisateur) : ~0,7 s message Telegram →
transaction _confirmée on-chain_, sur RPC Helius premium, taille déjà à 1,0 SOL.**
Un slot fait 0,4 s : vous atterrissez donc à ~1 slot du message, vous êtes **déjà
quasi same-slot**. Le diagnostic « vous êtes 2-6 s derrière sur RPC public » était
faux. Conséquences :

1. **Raboter encore la latence ne rapporte presque rien — vous êtes au plancher.**
   « Être premier dans la queue » à ce stade = gagner l'**ordre _à l'intérieur_ du
   slot**, et cet ordre s'achète : priority fee + **tip Jito**. Aujourd'hui, sans
   tip, vous êtes classé au hasard parmi les tx du même slot. **C'est le gain n°1**,
   pour 0,001-0,01 SOL/trade (§4.3). Ajouter Helius Sender (fan-out Jito+SWQoS,
   gratuit, même compte Helius) route la tx là où le tip compte.
2. **Pour passer _devant_ avant que la queue existe** (avant le post), un seul
   levier : le signal on-chain. Le KOL achète avant de poster ; ses wallets tournent
   à chaque call, donc on ne suit pas le wallet, on **remonte son financement**
   (§2.1). Ne marche que pour les KOL au financement traçable — sinon on court le
   post, et le post se gagne au tip (point 1).
3. **Le build local de la tx** (§3) enlève l'aller-retour PumpPortal : ~0,1-0,2 s +
   0,5 % de frais/trade économisés. Utile, pas transformateur à votre niveau.

**Périmètre demandé : « fast au buy pour le moment ».** Le plan est recentré sur le
buy. Les exits/PnL sont mis en différé à votre demande — un seul rappel, non répété :
`calls.csv` ne contient **aucune sortie** (zéro entry/exit/pnl sur les trades réels),
donc l'EV par canal est aujourd'hui inconnue ; à 2 SOL c'est le vrai risque, mais
c'est votre appel (§7 gardé pour plus tard).

**Ne pas commencer par monter `BUY_SOL`.** À 0,7 s-confirmé, la latence est réglée ;
ce qui reste à sécuriser avant 2 SOL, c'est le tip, l'impact de curve (§5) et le
dédup persistant (§10). Monter la taille en dernier.

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

### 2.1 Copier l'achat du KOL malgré les wallets tournants : remonter le financement

Le KOL achète on-chain **avant** de poster. Toute personne qui lit le post est en
retard par construction. Problème réel constaté : **le wallet d'achat change à
chaque call** — suivre un wallet fixe ne marche pas. Ce qui marche : un wallet
frais doit être **financé** avant d'acheter, et c'est le financement qui trahit.

**Méthode 1 — la chaîne de financement** :
1. Pour 5-10 calls passés : retrouver le wallet acheteur (le gros achat dans les
   minutes précédant le post — Solscan/GMGN sur le mint), puis regarder **d'où est
   venu son SOL** : première transaction entrante du wallet
   (`getSignaturesForAddress` + parse, ou un clic sur Solscan). Remonter 1-2 hops
   si besoin.
2. Deux cas de figure :
   - **Un financeur commun** apparaît (wallet « distributeur » du KOL, parfois
     derrière un hop) : c'est **lui** qu'on streame, pas les wallets d'achat.
     Watch-set gRPC dynamique : quand le financeur envoie du SOL à une adresse
     fraîche → ajouter cette adresse à la volée au `accountInclude` de la
     subscription Yellowstone → son premier achat pump.fun
     (`6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`) = signal, détecté ~100-300 ms
     après inclusion. Le financement précède l'achat de plusieurs minutes ou
     heures : la rotation par call ne protège pas contre ça.
   - **Financement direct depuis un CEX** sans hop : quasi intraçable (les hot
     wallets financent des milliers d'adresses). Pour ce KOL, la voie on-chain est
     morte → tout miser sur la course au post (§3-§4). Re-tester périodiquement,
     les habitudes changent.
3. Valider la stabilité du schéma sur l'historique **avant** de trader dessus,
   et re-valider en continu.

**Méthode 2 — détecter l'entourage (fallback, bruité)** : le cercle proche achète
souvent dans les secondes qui suivent le KOL, avant le post public. Stream gRPC sur
le programme pump.fun entier, trigger « N wallets frais achètent > X SOL en M slots
sur un token de moins de T minutes ». Toujours devant le post, mais faux positifs
élevés — à backtester sur les calls loggés et à trader en taille réduite uniquement.

**Outils d'investigation** (étape 1, pas l'exécution) : Solscan pour le graphe de
financement ; kolscan.io, labels GMGN/Arkham, Cielo, MadeOnSol pour partir des
identités.

**Fournisseurs gRPC** (juillet 2026) : Helius **LaserStream** (inclus au plan
Business 499 $/mois — à vérifier selon votre plan premium actuel, peut-être déjà
disponible) ; flat moins cher : **AllenHark** ~99 $/mois, **Shyft** ~199 $/mois,
**SolanaTracker** ~200 €/mois ; **Jito ShredStream** gratuit sur approbation
(décodage non trivial, pour plus tard). Bande passante filtrée : négligeable.

**Impact** : signal des secondes aux minutes avant tous les bots du canal — le seul
levier qui met *devant* au lieu d'« aussi vite que ». **Limite honnête** : ça ne
marche que si le KOL a un pattern de financement ; sinon, le jeu est la course au
post, et elle se gagne aux §3-§4. Les deux pipelines coexistent (dédup par mint,
déjà en place via `bought`).

### 2.2 Réception Telegram : déjà rapide ici — sécuriser la queue de distribution

Mesuré sur ce setup : ~0,7 s message→buy, réception comprise — les délais de fan-out
de 20-45 s rapportés par de vieilles issues Telethon (#3150, #652 : comptes passifs,
canaux géants, observations 2018-2021) ne s'appliquent pas ici. L'enjeu n'est donc
pas le gain médian mais la **variance** : le call où la livraison prend 3-5 s est
précisément celui où tout le monde se rue. Mesures d'assurance, par ordre d'utilité :

- **Compte(s) dédié(s) propre(s)** : numéro européen (→ home DC Amsterdam, DC2/DC4),
  abonné **uniquement** aux canaux cibles, éventuellement Premium ⚠️ (effet plausible,
  non prouvé). Le compte actuel, s'il suit des dizaines de canaux, est déprioritisé.
- **3-5 comptes/sessions Telethon en parallèle**, on garde le premier
  `UpdateNewChannelMessage` reçu (dédup par message id). L'ordre de fan-out par
  abonné est quasi aléatoire : la course en parallèle écrase la queue de latence.
- **Poller actif ~1 Hz** en filet : `GetHistoryRequest`/`GetChannelDifference` sur le
  canal cible (sous les flood-limits). Garde le canal « chaud » côté serveur Telegram
  et rattrape le call rare où le push tarde — c'est de l'assurance sur la variance,
  pas un gain médian (votre médiane est déjà bonne).
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

Baseline mesurée : **~0,7 s message → tx confirmée** (≈ 1 slot du message).

| Étape | Actuel | Cible | Levier |
|---|---|---|---|
| Signal (post→bot) | inclus dans les 0,7 s | idem (déjà bon) | variance couverte §2.2 ; **avant le post** via financement §2.1 |
| Build tx | ~0,1-0,3 s (RTT PumpPortal) | <5 ms | build local §3 (+ 0,5 % de frais économisés) |
| Envoi→confirmé | dans le slot, **sans tip = ordre aléatoire dans le slot** | même slot, **en tête** | priority fee + tip Jito §4.3 + Sender §4.1 |
| **Total** | **~0,7 s, position non prioritaire** | **~0,5 s, prioritaire dans le slot** | — |

Le gain n'est pas « moins de secondes » (il n'y en a presque plus à prendre) mais
« premier _dans_ le slot où vous êtes déjà ».

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

**État des lieux lu dans `calls.csv`** : les trades réels du 10-12 juillet
(0,001 → 0,43 → 0,4 → 1,0 SOL, 4+ canaux) n'ont **ni entry, ni exit, ni PnL**
enregistrés — l'EV par canal/KOL est incalculable avec ces données. Et le mint
`4t1xh…pump` a été acheté **3 fois en 15 minutes** (16:25, 16:35, 16:39) : le
dédup `bought` vit en mémoire, chaque restart repart de zéro — à 2 SOL/trade, ce
bug seul coûte 4-6 SOL sur un incident. Ces deux corrections passent avant toute
optimisation de latence.

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

Recalé sur le périmètre « fast au buy » et une baseline déjà à 0,7 s-confirmé.
L'ordre suit le rapport gain/effort réel, pas l'ambition théorique.

1. **Tip + priority fee dynamiques** (§4.3) via Helius Sender (§4.1) — même compte
   Helius, gratuit, quelques heures de dev. C'est le levier « premier dans le slot »
   le plus rentable et le plus rapide à poser. *Gate : sur 2 tx concurrentes dans un
   même slot, la vôtre passe devant (comparer l'ordre intra-slot avant/après).*
2. **Dédup persistant + `solders` requirements** (§10, §12) — corrige le rachat
   x3 observé ; indispensable avant de monter la taille. *Gate : un restart en
   pleine position ne rachète pas le mint.*
3. **Build local de la tx** (§3) : enlève l'aller-retour PumpPortal, -0,1-0,2 s +
   0,5 % de frais. *Gate : tx construite et signée sans appel réseau sortant hors
   send ; parité de résultat vs PumpPortal sur 20 trades.*
4. **Impact de curve dynamique** (§5) : lire l'état de la curve, calculer l'impact,
   capper la taille (curves fraîches ≠ migrées, vous avez dit « ça varie »).
   *Gate : le bot refuse/réduit un ticket dont l'impact projeté dépasse le seuil.*
5. **Signal on-chain** (§2.1) sur 2-3 KOL au financement traçable — le seul « devant
   le post ». *Gate : détection avant le post sur >50 % des calls de ces KOL.*
6. **Scaling** : 1 → 1,5 → 2 SOL par paliers, en surveillant le slippage réalisé
   (l'impact §5 croît avec la taille). *Gate : slippage réalisé conforme au calcul
   à chaque palier.*
7. **(Différé, à ta demande) Exits + EV par canal** (§7, §8) — le jour où tu veux
   savoir si tu es réellement profitable et sur quel canal.

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
- [ ] **Dédup persistant** : seeder `bought` depuis `calls.csv` au démarrage
      (+ TTL) — bug observé le 10/07 : même mint acheté 3 fois après restarts
- [ ] **Enregistrer les sorties** : chaque sell (auto ou manuel) écrit exit/pnl
      dans `calls.csv` — aujourd'hui aucune ligne réelle n'a de PnL
- [ ] `logger.py` : colonnes latence/slots/slippage réalisé/prix à +5s/+30s/+2min/
      +10min ; stats par KOL ; kill-switch
- [ ] `requirements.txt` : corriger `solder` → `solders` (typo actuelle), ajouter
      `httpx`, `uvloop`, `cryptg`, client gRPC (`yellowstone-grpc` / `grpcio`)

Ops :
- [ ] VPS Amsterdam, process 24/7 (systemd) — le runtime actuel est un poste
      Windows (`run_all.bat`) : migrer l'exécution sur le VPS, garder le poste
      comme console
- [ ] Sessions Telegram chaudes
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
