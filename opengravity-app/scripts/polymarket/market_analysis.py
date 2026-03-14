"""
Polymarket Market Analysis — Deep Scan v2
Analiza mercados activos, detecta arbitraje, categoriza y busca patrones.
Usa outcomePrices de Gamma API (no requiere CLOB orderbook).
"""
import httpx
import json
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone

GAMMA = "https://gamma-api.polymarket.com"
CLOB  = "https://clob.polymarket.com"

# ── 1. Fetch all active markets ──────────────────────────────────────────────

def fetch_markets(limit=200, max_pages=4):
    """Fetch top markets by volume, paginated."""
    all_markets = []
    offset = 0
    for page in range(max_pages):
        try:
            resp = httpx.get(f"{GAMMA}/markets", params={
                "active": "true",
                "closed": "false",
                "limit": limit,
                "offset": offset,
                "_sort": "volume:desc",
            }, timeout=20)
            batch = resp.json()
            if not batch:
                break
            all_markets.extend(batch)
            if len(batch) < limit:
                break
            offset += limit
        except Exception as e:
            print(f"  [WARN] Error fetching offset {offset}: {e}")
            break
    return all_markets


def parse_json_field(val):
    """Parse a field that might be JSON string or already a list."""
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return []
    return []


# ── 2. Categorization ────────────────────────────────────────────────────────

CATEGORY_KEYWORDS = {
    "sports": [
        "nba", "nfl", "mlb", "nhl", "premier league", "champions league",
        "world cup", "super bowl", "playoff", "game ", "match",
        "win the", "championship", "mvp", "scoring", "goals", "touchdown",
        "la liga", "bundesliga", "serie a", "ufc", "fight", "boxing",
        "tennis", "grand slam", "f1 ", "formula 1", "ncaa", "march madness",
        "tournament", "seed", "bracket", "final four", "sweet 16",
        "stanley cup", "world series", "pennant", "division",
        "lakers", "celtics", "warriors", "yankees", "dodgers",
        "manchester", "liverpool", "arsenal", "chelsea", "barcelona", "real madrid",
        "draft", "trade deadline", "free agent", "relegat",
        "fifa", "club world", "masters tournament", "pga", "golf",
        "colombian", "liga betplay", "copa ",
        "conference finals", "eastern", "western",
        "rookie of the year", "defensive player",
    ],
    "crypto": [
        "bitcoin", "btc", "ethereum", "eth", "solana", "sol",
        "crypto", "token", "defi", "nft", "blockchain", "halving",
        "market cap", "altcoin", "memecoin", "doge", "xrp",
        "binance", "coinbase", "sec crypto", "polymarket",
    ],
    "politics": [
        "president", "election", "congress", "senate", "house",
        "democrat", "republican", "trump", "biden", "governor",
        "supreme court", "legislation", "bill pass", "veto",
        "vote", "poll", "primary", "caucus", "electoral",
        "cabinet", "secretary", "impeach", "executive order",
        "prime minister", "parliament", "nomination", "nominee",
        "tariff", "sanction", "ceasefire", "war ",
    ],
    "economics": [
        "fed ", "interest rate", "inflation", "cpi", "gdp",
        "recession", "unemployment", "jobs report", "nasdaq",
        "s&p ", "dow ", "stock market", "oil price", "gold price",
    ],
    "tech": [
        " ai ", "artificial intelligence", "chatgpt", "openai", "google",
        "apple", "microsoft", "tesla", "spacex", "launch",
        "ipo", "acquisition", "gta",
    ],
    "entertainment": [
        "oscar", "grammy", "emmy", "box office", "movie", "album",
        "spotify", "netflix", "disney", "streaming",
        "reality tv", "bachelor", "survivor",
    ],
}


def categorize_market(question: str, description: str = "") -> str:
    text = (" " + question + " " + description + " ").lower()
    scores = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scores[cat] = score
    if not scores:
        return "other"
    return max(scores, key=scores.get)


# ── 3. Tournament/Group Detection ────────────────────────────────────────────

def detect_groups(markets: list) -> dict:
    """Group markets by shared event/tournament."""
    groups = defaultdict(list)

    # Strategy 1: Group by event title (from events field)
    for m in markets:
        events = m.get("_events", [])
        for ev in events:
            title = ev.get("title", "")
            if title and len(title) > 10:
                groups[f"event:{title}"].append(m)

    # Strategy 2: Pattern-based grouping
    group_patterns = [
        (r"([\w\s]+) win (?:the )?(nba|nfl|nhl|mlb|premier league|champions league|stanley cup|world series|fifa|copa|masters|la liga|bundesliga|serie a|ligue 1)[\w\s]*", 2),
        (r"([\w\s]+) (?:win|make|reach) (?:the )?([\w\s]+ finals)", 2),
        (r"([\w\s]+) (?:win|get) (?:the )?([\w\s]*(?:mvp|rookie|award|nomination))", 2),
        (r"([\w\s]+) (?:presidential|democratic|republican) (nomination|election)", 0),
    ]

    for m in markets:
        q = m["question"]
        for pattern, group_idx in group_patterns:
            match = re.search(pattern, q, re.IGNORECASE)
            if match:
                try:
                    key = match.group(group_idx).strip().lower()
                    if len(key) > 3:
                        groups[f"pattern:{key}"].append(m)
                except Exception:
                    pass

    # Strategy 3: Shared question prefixes
    from itertools import combinations
    prefix_groups = defaultdict(list)
    for m in markets:
        # Common question patterns
        q = m["question"]
        # "X win Y?" -> group by Y
        win_match = re.search(r"win (?:the )?(.*?)[\?\.]?\s*$", q, re.IGNORECASE)
        if win_match:
            target = win_match.group(1).strip().rstrip("?. ")
            if len(target) > 5:
                prefix_groups[f"win:{target.lower()}"].append(m)

    for k, v in prefix_groups.items():
        if len(v) >= 2 and k not in groups:
            groups[k] = v

    # Deduplicate and filter
    final = {}
    seen_cids = set()
    for key in sorted(groups.keys(), key=lambda k: -len(groups[k])):
        mlist = groups[key]
        unique = []
        for m in mlist:
            cid = m["condition_id"]
            if cid not in seen_cids:
                unique.append(m)
                seen_cids.add(cid)
        if len(unique) >= 2:
            final[key] = unique

    return final


# ── 4. Main Analysis ─────────────────────────────────────────────────────────

def main():
    print("=" * 80)
    print("POLYMARKET DEEP MARKET ANALYSIS v2")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 80)

    # Step 1: Fetch all markets
    print("\n[1/6] Fetching active markets from Gamma API...")
    all_markets_raw = fetch_markets(limit=200, max_pages=5)
    print(f"  Total markets fetched: {len(all_markets_raw)}")

    # Step 2: Parse and filter
    print("\n[2/6] Parsing and filtering (vol > $50k, liq > $2k)...")
    all_parsed = []
    filtered = []

    for m in all_markets_raw:
        vol = float(m.get("volume", 0) or 0)
        liq = float(m.get("liquidity", 0) or 0)

        outcomes = parse_json_field(m.get("outcomes", []))
        outcome_prices = parse_json_field(m.get("outcomePrices", []))
        clob_token_ids = parse_json_field(m.get("clobTokenIds", []))

        # Parse events for grouping
        events_raw = m.get("events", [])
        if isinstance(events_raw, str):
            try:
                events_raw = json.loads(events_raw)
            except Exception:
                events_raw = []

        parsed = {
            "condition_id": m.get("conditionId", ""),
            "question": m.get("question", ""),
            "description": (m.get("description", "") or "")[:300],
            "volume": vol,
            "volume_24h": float(m.get("volume24hr", 0) or 0),
            "liquidity": liq,
            "end_date": m.get("endDate", ""),
            "outcomes": outcomes,
            "outcome_prices": [float(p) for p in outcome_prices] if outcome_prices else [],
            "clob_token_ids": clob_token_ids,
            "spread": float(m.get("spread", 0) or 0),
            "best_bid": float(m.get("bestBid", 0) or 0),
            "best_ask": float(m.get("bestAsk", 0) or 0),
            "last_trade_price": float(m.get("lastTradePrice", 0) or 0),
            "one_day_change": float(m.get("oneDayPriceChange", 0) or 0),
            "one_week_change": float(m.get("oneWeekPriceChange", 0) or 0),
            "_events": events_raw,
        }
        parsed["category"] = categorize_market(parsed["question"], parsed["description"])
        all_parsed.append(parsed)

        if vol >= 50000 and liq >= 2000:
            filtered.append(parsed)

    print(f"  Total parsed: {len(all_parsed)}")
    print(f"  Markets passing filters: {len(filtered)}")

    # Additional filter tiers
    tier1 = [m for m in filtered if m["volume"] >= 1000000 and m["liquidity"] >= 50000]
    tier2 = [m for m in filtered if 200000 <= m["volume"] < 1000000 and m["liquidity"] >= 10000]
    tier3 = [m for m in filtered if m["volume"] < 200000]
    print(f"  Tier 1 (vol>$1M, liq>$50k): {len(tier1)}")
    print(f"  Tier 2 (vol $200k-$1M, liq>$10k): {len(tier2)}")
    print(f"  Tier 3 (vol<$200k): {len(tier3)}")

    # Step 3: Categorize
    print("\n[3/6] Categorizing markets...")
    cat_counts = Counter(m["category"] for m in filtered)
    for cat, cnt in cat_counts.most_common():
        print(f"  {cat:15s}: {cnt:4d} ({cnt/len(filtered)*100:.1f}%)")

    # Step 4: YES+NO sum analysis (arbitrage detection)
    print("\n[4/6] Analyzing YES+NO price sums (arbitrage detection)...")
    sum_data = []
    arb_opportunities = []

    for m in filtered:
        prices = m["outcome_prices"]
        outcomes = m["outcomes"]

        if len(prices) >= 2 and len(outcomes) >= 2:
            # For binary markets (Yes/No)
            yes_idx = None
            no_idx = None
            for i, o in enumerate(outcomes):
                if o.lower() == "yes":
                    yes_idx = i
                elif o.lower() == "no":
                    no_idx = i

            if yes_idx is not None and no_idx is not None:
                yes_p = prices[yes_idx]
                no_p = prices[no_idx]
                price_sum = yes_p + no_p
                edge_pct = abs(1.0 - price_sum) * 100

                entry = {
                    "question": m["question"][:100],
                    "condition_id": m["condition_id"],
                    "yes_price": round(yes_p, 4),
                    "no_price": round(no_p, 4),
                    "sum": round(price_sum, 4),
                    "edge_pct": round(edge_pct, 2),
                    "volume": m["volume"],
                    "liquidity": m["liquidity"],
                    "category": m["category"],
                    "spread": m["spread"],
                }
                sum_data.append(entry)

                if price_sum < 0.92 or price_sum > 1.08:
                    arb_opportunities.append(entry)

    print(f"  Binary markets with prices: {len(sum_data)}")
    print(f"  Arb opportunities (sum < 0.92 or > 1.08): {len(arb_opportunities)}")

    # Sum distribution
    if sum_data:
        sums = [s["sum"] for s in sum_data]
        avg_sum = sum(sums) / len(sums)
        min_sum = min(sums)
        max_sum = max(sums)
        under_98 = len([s for s in sums if s < 0.98])
        over_102 = len([s for s in sums if s > 1.02])
        tight = len([s for s in sums if 0.99 <= s <= 1.01])
        print(f"  Avg sum: {avg_sum:.4f}")
        print(f"  Min sum: {min_sum:.4f}, Max sum: {max_sum:.4f}")
        print(f"  Tight (0.99-1.01): {tight}")
        print(f"  Under 0.98: {under_98}, Over 1.02: {over_102}")

        # Show top deviations
        sorted_by_deviation = sorted(sum_data, key=lambda x: abs(1.0 - x["sum"]), reverse=True)
        print(f"\n  Top 15 deviations from 1.0:")
        for s in sorted_by_deviation[:15]:
            flag = " *** ARB" if s["sum"] < 0.92 or s["sum"] > 1.08 else ""
            print(f"    SUM={s['sum']:.4f} (edge={s['edge_pct']:.1f}%) YES={s['yes_price']:.3f} NO={s['no_price']:.3f} | {s['question'][:70]}{flag}")
    else:
        avg_sum = min_sum = max_sum = 0

    # Step 5: Keyword analysis
    print("\n[5/6] Analyzing keywords...")
    all_words = []
    stopwords = {
        "will", "the", "this", "that", "what", "who", "how", "does",
        "have", "has", "are", "was", "were", "been", "being", "for",
        "with", "from", "more", "than", "about", "before", "after",
        "above", "below", "between", "into", "through", "during",
        "each", "which", "their", "there", "here", "where", "when",
        "and", "but", "not", "any", "all", "most", "some", "other",
        "over", "under", "again", "once", "then", "too",
        "very", "can", "just", "should", "now", "yes", "2025", "2026",
    }
    for m in filtered:
        words = re.findall(r'\b[a-zA-Z]{3,}\b', m["question"].lower())
        meaningful = [w for w in words if w not in stopwords]
        all_words.extend(meaningful)

    keyword_counts = Counter(all_words).most_common(50)
    print(f"  Top 25 keywords:")
    for kw, cnt in keyword_counts[:25]:
        print(f"    {kw:20s}: {cnt}")

    # Step 6: Tournament groups
    print("\n[6/6] Detecting tournament/event groups...")
    groups = detect_groups(filtered)

    tournament_analysis = []
    for group_name, group_markets in sorted(groups.items(), key=lambda x: -len(x[1])):
        prices_list = []
        for gm in group_markets:
            op = gm.get("outcome_prices", [])
            yes_p = op[0] if op else 0
            prices_list.append({
                "question": gm["question"][:80],
                "yes_price": round(yes_p, 4),
                "volume": gm["volume"],
            })

        if len(prices_list) >= 2:
            total = sum(p["yes_price"] for p in prices_list)
            tournament_analysis.append({
                "group": group_name,
                "num_markets": len(prices_list),
                "markets": sorted(prices_list, key=lambda x: -x["yes_price"]),
                "total_probability": round(total, 4),
                "deviation_from_100_pct": round(abs(1.0 - total) * 100, 2),
                "note": "OVERPRICED" if total > 1.15 else "UNDERPRICED" if total < 0.85 else "NORMAL",
            })

    tournament_analysis.sort(key=lambda x: -x["deviation_from_100_pct"])
    print(f"  Groups found: {len(tournament_analysis)}")
    for ta in tournament_analysis[:20]:
        note_flag = " <<<" if ta["note"] != "NORMAL" else ""
        print(f"    [{ta['num_markets']:2d} mkts] sum={ta['total_probability']:.2f} ({ta['note']:11s}) | {ta['group'][:60]}{note_flag}")

    # ── Build & print large price movements ──────────────────────────────────
    print("\n[BONUS] Markets with large 24h price changes:")
    big_movers = sorted(filtered, key=lambda x: abs(x["one_day_change"]), reverse=True)
    for bm in big_movers[:15]:
        print(f"  {bm['one_day_change']:+.3f} | price={bm['last_trade_price']:.3f} liq=${bm['liquidity']:,.0f} | {bm['question'][:70]}")

    # ── Build Report ──────────────────────────────────────────────────────────

    category_details = {}
    for cat, count in cat_counts.items():
        cat_markets = [m for m in filtered if m["category"] == cat]
        avg_vol = sum(m["volume"] for m in cat_markets) / len(cat_markets) if cat_markets else 0
        avg_liq = sum(m["liquidity"] for m in cat_markets) / len(cat_markets) if cat_markets else 0
        avg_24h = sum(m["volume_24h"] for m in cat_markets) / len(cat_markets) if cat_markets else 0
        category_details[cat] = {
            "count": count,
            "avg_volume": round(avg_vol),
            "avg_liquidity": round(avg_liq),
            "avg_volume_24h": round(avg_24h),
            "pct_of_total": round(count / len(filtered) * 100, 1),
        }

    # Recommended base rates based on actual price distributions
    base_rate_recs = {}
    for kw, cnt in keyword_counts[:30]:
        if cnt >= 5:
            matching = [m for m in filtered if kw in m["question"].lower()]
            prices = [m["outcome_prices"][0] for m in matching if m["outcome_prices"]]
            if prices:
                avg_p = sum(prices) / len(prices)
                base_rate_recs[kw] = {
                    "count": cnt,
                    "avg_yes_price": round(avg_p, 3),
                    "min_price": round(min(prices), 3),
                    "max_price": round(max(prices), 3),
                    "suggested_base_rate": round(avg_p, 2),
                }

    # Missing signal patterns analysis
    missing_signals = [
        {
            "name": "TIME_DECAY",
            "description": "Mercados cerca de resolucion (<7 dias) con precios entre 0.15-0.85 tienen theta negativo implicito. Si el evento ya esta decidido, el precio deberia estar cerca de 0 o 1.",
            "how_to_implement": "Filtrar mercados con end_date - now < 7d y 0.15 < price < 0.85. Alta probabilidad de movimiento rapido.",
        },
        {
            "name": "VOLUME_SPIKE",
            "description": "Picos de volumen 24h > 3x promedio semanal suelen preceder movimientos de precio informados.",
            "how_to_implement": "Comparar volume24hr con volume1wk/7. Si ratio > 3, senalar como posible informed trading.",
        },
        {
            "name": "CROSS_MARKET_ARB",
            "description": "En torneos/grupos, la suma de probabilidades debe ser ~100%. Desviaciones significativas son oportunidades.",
            "how_to_implement": "Usar los tournament_groups detectados. Si sum > 1.15 o < 0.85, buscar el outlier.",
        },
        {
            "name": "SPREAD_CAPTURE",
            "description": "Mercados con spread > 5% permiten market making pasivo. Comprar en bid, vender en ask.",
            "how_to_implement": "Filtrar mercados con spread > 0.05 y liquidity > $5k. Colocar ordenes en ambos lados.",
        },
        {
            "name": "OPENING_LINE_COMPARISON",
            "description": "Comparar precio actual con precio historico de apertura. Grandes desviaciones sin noticias = overreaction.",
            "how_to_implement": "Necesita almacenar precios de apertura. Calcular delta vs apertura y filtrar >20pts.",
        },
    ]

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_markets_scanned": len(all_markets_raw),
        "markets_passing_filters": len(filtered),
        "filter_criteria": {"min_volume_usd": 50000, "min_liquidity_usd": 2000},
        "tiers": {
            "tier1_vol_gt_1M": len(tier1),
            "tier2_vol_200k_1M": len(tier2),
            "tier3_vol_lt_200k": len(tier3),
        },

        "categories": dict(cat_counts.most_common()),
        "category_details": category_details,

        "price_sum_analysis": {
            "binary_markets_checked": len(sum_data),
            "avg_yes_no_sum": round(avg_sum, 4) if sum_data else None,
            "min_sum": round(min_sum, 4) if sum_data else None,
            "max_sum": round(max_sum, 4) if sum_data else None,
            "tight_spread_0_99_1_01": len([s for s in sum_data if 0.99 <= s["sum"] <= 1.01]),
            "moderate_spread_0_95_1_05": len([s for s in sum_data if 0.95 <= s["sum"] <= 1.05]) - len([s for s in sum_data if 0.99 <= s["sum"] <= 1.01]),
            "wide_spread_outside_5pct": len([s for s in sum_data if s["sum"] < 0.95 or s["sum"] > 1.05]),
            "top_deviations": sorted(sum_data, key=lambda x: abs(1.0 - x["sum"]), reverse=True)[:20],
        },

        "arb_opportunities_8pct": arb_opportunities,
        "arb_count": len(arb_opportunities),

        "top_keywords": [{"keyword": kw, "count": cnt} for kw, cnt in keyword_counts[:40]],

        "tournament_groups": tournament_analysis[:25],
        "tournament_count": len(tournament_analysis),

        "big_movers_24h": [
            {
                "question": bm["question"][:100],
                "price_change_24h": bm["one_day_change"],
                "current_price": bm["last_trade_price"],
                "liquidity": bm["liquidity"],
                "category": bm["category"],
            }
            for bm in big_movers[:20]
        ],

        "recommended_base_rates": base_rate_recs,
        "missing_signal_patterns": missing_signals,

        "recommendations": [],
    }

    # Generate actionable recommendations
    recs = []
    recs.append(f"TOTAL: {len(filtered)} mercados operables (vol>$50k, liq>$2k) de {len(all_markets_raw)} escaneados")

    if cat_counts.get("sports", 0) > len(filtered) * 0.5:
        recs.append(f"DEPORTES DOMINA: {cat_counts['sports']}/{len(filtered)} ({cat_counts['sports']/len(filtered)*100:.0f}%) — URGENTE agregar base rates deportivos al EdgeDetector")

    crypto_count = cat_counts.get("crypto", 0)
    if crypto_count < 10:
        recs.append(f"CRYPTO DEBIL: Solo {crypto_count} mercados crypto con liquidez — considerar bajar threshold de liquidez para crypto")

    if arb_opportunities:
        recs.append(f"ARBITRAJE DIRECTO: {len(arb_opportunities)} mercados con YES+NO sum desviada >8% — verificar si es error de datos o oportunidad real")

    for ta in tournament_analysis[:5]:
        if ta["note"] != "NORMAL":
            recs.append(f"GRUPO ARB '{ta['group']}': {ta['num_markets']} mercados suman {ta['total_probability']:.2f} ({ta['note']})")

    # Volume spike detection
    vol_spike_candidates = [m for m in filtered if m["volume_24h"] > 0 and m["volume"] > 0]
    for m in vol_spike_candidates:
        weekly_avg = m["volume"] / max((datetime.now(timezone.utc) - datetime.fromisoformat(m["end_date"].replace("Z", "+00:00"))).days, 1) if m["end_date"] else 0
        # Simple heuristic: if 24h vol > 10% of total vol, it's a spike
        if m["volume_24h"] > m["volume"] * 0.1 and m["volume_24h"] > 50000:
            pass  # Will be captured in big_movers

    # Time decay candidates
    time_decay = []
    now = datetime.now(timezone.utc)
    for m in filtered:
        if m["end_date"]:
            try:
                end = datetime.fromisoformat(m["end_date"].replace("Z", "+00:00"))
                days_left = (end - now).days
                price = m["outcome_prices"][0] if m["outcome_prices"] else 0
                if 0 < days_left <= 7 and 0.15 < price < 0.85:
                    time_decay.append({
                        "question": m["question"][:80],
                        "days_left": days_left,
                        "price": round(price, 3),
                        "liquidity": m["liquidity"],
                    })
            except Exception:
                pass

    if time_decay:
        recs.append(f"TIME DECAY: {len(time_decay)} mercados resuelven en <7 dias con precios lejos de 0/1 — alta probabilidad de movimiento")
        report["time_decay_candidates"] = sorted(time_decay, key=lambda x: x["days_left"])[:15]

    report["recommendations"] = recs

    # ── Print Final Report ────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("REPORTE JSON COMPLETO")
    print("=" * 80)
    print(json.dumps(report, indent=2, ensure_ascii=False))

    # Save
    out_path = "C:/Users/ijsal/OneDrive/Documentos/OpenGravity/opengravity-app/scripts/polymarket/data/market_analysis_report.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\nReporte guardado en: {out_path}")

    return report


if __name__ == "__main__":
    main()
