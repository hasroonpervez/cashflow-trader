# The verdict in one paragraph

No, he is not right: the language is not the problem, and switching it would make the app slower to build, riskier, and no faster to use. Six specialists measured the whole stack on the actual hardware and the arithmetic is not close. The entire theoretical prize for replacing Python in the API layer is 0.060 ms per request (measured: Python at 0.105 ms per HTTP round trip versus 0.045 ms for the fastest runtime tested on this box), and the entire prize for rewriting the quant core in Rust is about 0.013 ms on the hottest path. The round trip through Cloudflare to his phone measures 40 ms on average (min 36 ms, max 52 ms) and 131 to 202 ms on a cold connection. So a language migration moves between 0.03% and 0.15% of what he actually feels, in exchange for hand-writing Baum-Welch, Wilson bounds and bootstrap confidence intervals in a language with no mature library for any of them, and deleting the 852 tests that just caught 88 defects including an inverted vanna sign and a Kelly clip that could size above 100% of bankroll. But his instinct that "something is wrong" is correct, and the specialists found it: there is a real 12 to 17 ms defect in the options code (scalar `scipy.stats.norm.cdf` calls, fixable in an afternoon for a 260x to 1000x win), and, far more importantly, the app currently asks the network for things it could already have in the browser. Apps like x.com feel fast because they do not make you wait for the network on interactions, not because they are written in Rust. That is the whole answer, and it is achievable with roughly two days of work and zero new languages.

# What actually determines whether this app feels fast

Ranked by milliseconds removed from a single user interaction (a tap, a sort, a tab switch, a drill-in). All figures are measured, either on the target machine or from the sources named.

| Rank | Lever | Milliseconds it removes | Evidence |
|---|---|---|---|
| 1 | **Do not cross the network at all.** Load one precomputed snapshot into memory, serve every subsequent sort, filter, tab and drill-in from it. | **20 to 80 ms per interaction** (40 ms typical). Local reads measured at 0.4 ms via the browser Cache API, 0.8 ms via IndexedDB, under 0.05 ms for an in-memory filter and sort of 500 rows. | Measured in Chrome 148 on the box: Cloudflare RTT 40.4 ms avg (36.0 min, 52.2 max); Cache API read and parse of the 86,518 byte payload 0.4 ms. That is a 100x gap. |
| 2 | **Take the MacBook and the tunnel off the critical path for cold loads.** Cloudflare Cache Rules plus async stale-while-revalidate. | **131 to 202 ms** on a cold load, and it removes origin timeouts from user-visible latency permanently. | Measured cold DNS plus connect plus TLS plus TTFB to a Cloudflare-fronted origin: 131 to 202 ms. Async SWR shipped to the free plan 2026-02-26 ([Cloudflare changelog](https://developers.cloudflare.com/changelog/post/2026-02-26-async-stale-while-revalidate)). |
| 3 | **Prefetch on hover and on viewport.** SvelteKit's `data-sveltekit-preload-data="hover"` (already on by default) plus Chrome Speculation Rules. | **20 to 80 ms, converted to 0 ms perceived**, because the fetch happens during the 200 to 400 ms a human takes between hovering and clicking. | SvelteKit docs describe preloading as worth "an extra couple of hundred milliseconds" ([svelte.dev](https://svelte.dev/docs/kit/link-options)). Speculation Rules now trigger on mobile viewport heuristics 50 ms after an anchor appears ([Chrome docs](https://developer.chrome.com/docs/web-platform/prerender-pages)). |
| 4 | **Never let quant math run inside a request.** Workers precompute into Postgres; the API only reads materialised views. | **Up to 55 to 64 ms**, which is what it costs you when this rule is broken. | Measured: with the 12.6 ms greeks handler in the request path under load, the cheap dashboard endpoint went from 0.139 ms mean to 55.3 ms mean, p99 64 ms. Adding 4 Granian workers did not fix it (still 40.5 ms). Only removing the compute from the path did. |
| 5 | **Compress the response.** Brotli on API JSON. | **14.5 ms** on a 10 Mbps LTE phone, 5.8 ms on 25 Mbps. | Measured: the 22,118 byte dashboard payload compresses to 4,043 bytes, 18% of original. |
| 6 | **Render fewer rows.** Cap the initial table at 50 rows and virtualise the rest. | **12.8 ms** on the largest page. | Measured in Chrome 148: full DOM rebuild including forced layout is 0.9 ms at 50 rows (p95 1.3 ms) and 13.7 ms at 500 rows. |
| 7 | **Fix the scalar `scipy.stats.norm.cdf` calls in the options code.** | **12 to 17 ms per option chain**, plus roughly 20 ms per ticker of Monte Carlo waste. Zero of it is user-perceived today *if* rule 4 holds, but it is the difference between fresh data and stale data, and it is the one genuine defect in the backend. | Three specialists independently measured the 200-strike greeks loop at 12.35, 14.71 and 16.67 ms against your stated 12.6 ms baseline. Vectorised: 0.014 to 0.048 ms. Root cause: `scipy.stats.norm.cdf` costs 18.7 to 19.7 microseconds per scalar call versus 0.07 to 0.12 microseconds for a `math.erf` equivalent, a 164x to 263x gap in pure dispatch overhead. |
| 8 | **Speed up analytical scans (backtests).** DuckDB in process against Postgres. | **2,559 ms** on a backtest, which is a foreground wait when you run one. | Measured on the box with 9.3M rows: identical backtest SQL takes 2,659.6 ms in PostgreSQL 17, 100.6 ms via DuckDB `postgres_scanner`, 45.3 ms in native DuckDB. |
| 9 | **Choice of database.** | **At most 0.135 ms.** | Measured: the planned materialised-view read for a top-50 dashboard payload is 0.135 ms p50, 0.214 ms p99. No store on earth improves on that in a way a human can detect. |
| 10 | **Choice of API language and web framework.** | **0.060 ms.** | Measured on this box at concurrency 1: Python (Litestar 2.24 + Granian 2.8.1 + msgspec) 0.105 ms per full HTTP round trip, Deno 2.9.5 at 0.045 ms, Fastify 5.11 at 0.092 ms. At concurrency 8 and 64 the Python stack **beat** Fastify and raw `node:http` outright (19,421 rps and p99 5 ms versus Fastify's 15,708 rps and p99 8 ms), because Granian's HTTP layer is already Rust. |
| 11 | **Choice of quant compute language.** | **0.013 ms.** | Measured ceiling for a PyO3 or Rust rewrite of the greeks chain after vectorisation: about 0.001 ms of compute plus 0.032 ms irreducibly spent building 200 Python result dicts, versus 0.0141 ms plus 0.032 ms for vectorised numpy. |

**Language choice is levers 10 and 11, at the bottom, worth 0.060 ms and 0.013 ms.** Together that is 0.073 ms against a 40 ms round trip: 0.18%. A single frame at 120 Hz is 8.3 ms, so the entire language question is 1/114th of one frame.

One caveat about the baseline: two specialists reported the machine identifying as Apple M4, 10 cores, 16 GB rather than M3 Pro, 11 cores, 18 GB, and I confirmed that `/Users/hasroon/cashflow-trader/.venv-ci` runs **Python 3.9.6**, not the 3.12.13 in the brief. Python 3.9 went end of life in October 2025. The margins above are 100x to 1000x, so no conclusion changes, but the baseline should be corrected before the next round of measurement.

# Where a different technology genuinely wins

## 1. A service worker plus an immutable versioned snapshot. Game changer.

**What it is:** the background worker writes the whole dashboard as one JSON file at a versioned URL, for example `/api/snapshot/<build_id>.json`, marked `Cache-Control: public, max-age=31536000, immutable`. A tiny `/api/version` pointer says which build is current. The browser stores the snapshot and a service worker serves it from disk instead of the network.

**Measured win:** 0.4 ms local read versus 40 ms network read, a 100x gap, on every interaction after the first. On a cold reload it replaces a 131 to 202 ms handshake.

**Migration cost:** roughly 40 lines of JavaScript, half a day. Zero Python changes. No risk to the 852 tests. The one hazard is a botched service worker serving stale assets forever, so version the cache name off the build id and call `skipWaiting` and `clients.claim` deliberately.

**Should we do it: yes, first, before anything else on the frontend.**

## 2. Cloudflare Cache Rules, async stale-while-revalidate, HTTP/3. Game changer.

**What it is:** configuration only. Tell Cloudflare that your JSON responses are cacheable (by default they are not, because `application/json` is not in Cloudflare's default cacheable extension list), and set `Cache-Control: public, max-age=15, stale-while-revalidate=300` on the version pointer.

**Measured win:** the origin, meaning the MacBook and the tunnel, leaves the critical path entirely for cached responses. Since 2026-02-26 the first request after expiry gets stale content immediately while Cloudflare revalidates in the background, on the free plan ([Cloudflare changelog](https://developers.cloudflare.com/changelog/post/2026-02-26-async-stale-while-revalidate)). HTTP/3 is on by default and removes head of line blocking on lossy mobile links, which is the network this app is actually used on.

**Migration cost:** an afternoon of configuration. No code rewrite.

**Should we do it: yes.** Note the limit honestly: the tunnel hop is only removed for cached responses. Anything that must reach the MacBook still pays it, which is another argument for the precomputed snapshot.

## 3. Brotli on API responses. Real and immediate.

**Measured win:** 22,118 bytes to 4,043 bytes, saving 14.5 ms on 10 Mbps LTE and 5.8 ms on 25 Mbps 4G. That single header is worth 240 times more than the entire Python to Deno gap of 0.060 ms.

**Migration cost:** one line of middleware.

**Should we do it: yes, today.**

## 4. Vectorised numpy inside the existing Python. Game changer, and the biggest backend win available.

**What it is:** not a new technology at all. It is the numpy you already have, applied to code that currently loops one strike at a time. Your `modules/options.py` line 41 does `from scipy.stats import norm; _cdf = norm.cdf`, and the fallback path at line 49 (used only when scipy is missing) is an Abramowitz and Stegun approximation. The scipy scalar path is the slow one.

**Measured wins, all on your box, all with the 852 tests as the oracle:**
- 200-strike greeks chain: 12.35 to 16.67 ms down to 0.014 to 0.048 ms. That is 260x to 1043x.
- The intermediate, provably risk-free version: swapping scalar `scipy.stats.norm.cdf` for a `math.erf` equivalent gives 35.7x to 39x with **max absolute deviation 0.000e+00 across all six greeks over 200 strikes**. Bit identical. Verified independently by two specialists.
- `Opt.covered_calls` re-seeds `np.random.default_rng(seed=42)` inside the `iterrows` loop, so all 60 strikes draw the identical 10,000 path array. Hoisting it: 7.939 ms to 1.868 ms, max deviation 0.000e+00. On a 200-strike chain: 18.06 ms to 0.295 ms, 61x, again bit identical.
- The four `df.iterrows()` loops at `modules/options.py` lines 2480, 2509, 2546 and 2574: replacing them with zipped `.to_numpy()` columns is 2.44 ms to 0.034 ms per 200-row chain, 72x.

**Migration cost:** one to two days, one file, roughly 200 to 400 lines. Zero new dependencies. All 852 tests keep running unchanged and act as the safety net rather than the casualty.

**Should we do it: yes, this is item one on the whole list.** One trap: do **not** also replace the Monte Carlo PoP with its analytic closed form, even though it is 441x to 3,615x faster. It deviates by up to 0.60 percentage points and would silently rebaseline your PoP assertions.

## 5. DuckDB as an in-process query engine for backtests. Game changer, but only for scans.

**What it is:** a library you `pip install`, not a server and not a second database. You attach it to your live Postgres and it runs analytical scans much faster than Postgres can.

**Measured win on your box with 9.3M rows:** a realistic backtest (lag, 50-day SMA, win rate over 10 years of bars) takes 2,659.6 ms in PostgreSQL 17 and 100.6 ms through DuckDB's `postgres_scanner` with zero ETL, a 26x win. Native DuckDB over a Parquet copy is 45.3 ms, but that requires building and maintaining a Parquet lake for a further 55 ms. Other measured scans: 6M-row GEX aggregate 193.9 ms to 41.8 ms, a 2M by 1.3M row join 843.1 ms to 36.1 ms.

**Migration cost:** very low. One dependency, one line of SQL setup, no schema change, no test risk.

**Should we do it: yes, when you next run a backtest that annoys you.** Two hard rules from the measurements. Never put DuckDB on the dashboard read path: it is 8x to 24x **slower** than Postgres for point lookups (1.073 ms versus 0.044 ms) and costs about 30 ms of fixed metadata open per Parquet query. And never use a shared persistent `.duckdb` file as the handoff between the worker and the API: a writer gets "IO Error: Could not set lock on file" the moment any other process holds a read-only handle, so a long-lived API reader permanently locks out your ingest worker. Parquet has no such problem, verified across an atomic `os.replace`.

## 6. QuantLib, imported from Python. Real but modest, and it is a correctness win not a speed win.

**What it is:** the actual industry standard options library used in banks, BSD-3 licensed, available as `pip install QuantLib` (v1.43 shipped 2026-07-14 on a reliable quarterly cadence, [releases](https://github.com/lballabio/QuantLib/releases)). No C++ required.

**Measured win:** none on speed, and it would be slower per contract through SWIG than your vectorised numpy. The win is validated day-count conventions, holiday calendars, American and Bermudan exercise, and dividend handling, which you currently approximate or do not have. Given that an audit just found an inverted vanna sign, a battle-tested pricing engine you can cross-check against is worth more than microseconds.

**Migration cost:** near zero as a selective import. All 852 tests keep running and can be extended to cross-check your closed-form greeks against QuantLib's.

**Should we do it: not yet, but keep it on the shelf.** Reach for it the day you want American-option pricing or a real calendar engine. Interpreting it as "rewrite in C++" would be a catastrophe.

## 7. `pytest -n auto`. Real but modest, and it improves the thing you actually spend your life on.

**Measured win:** the real suite goes from 852 passed in 48.96 s to 852 passed in 22.82 s, a 2.1x speedup, both runs green. The ceiling is set by the 765 ms cost of importing numpy plus pandas plus scipy per worker.

**Migration cost:** one flag, one dev dependency. The only risk is tests sharing mutable global state, and all 852 already passed under `-n auto`, so that risk is measured at zero.

**Should we do it: yes, today.**

## 8. Polars. Real, larger than expected, and still not yet.

This is the one place where the conventional wisdom in your plan is measurably wrong, so it deserves an honest hearing. The claim "Polars only wins on millions of rows" is **false for your code shape**. Measured on your exact indicator pipeline: at 500 bars pandas takes 1.329 ms and Polars 0.254 ms, a **5.2x** win, and the advantage is *larger* at 500 rows than at 200,000 rows (2.9x), because at small sizes the cost is pandas' fixed per-call overhead across ten chained Series operations, which Polars collapses into a single plan. Restructured into one stacked 375,000-row frame with `.over(symbol)`, the whole 500-ticker scan goes from 679 ms to 14 ms, a 48x win. Numerical equivalence was verified to 1e-13 with NaN warm-up patterns matching exactly.

**So why not?** Because 679 ms to 14 ms saves 0.665 s on a background job that runs every 15 minutes for one user. It is invisible. And the cost is 62 call sites to convert plus every downstream consumer that relies on a pandas DatetimeIndex, `.iloc`, or index-aligned `.shift`, semantics Polars does not have at all because it has no row index. That is a multi-week migration across 25,646 lines, during which the audit's 88 fixed defects are exposed to regression.

**Should we do it: no, and revisit at a specific trigger:** when the universe exceeds roughly 5,000 tickers or you move to intraday bars. If you ever do migrate, migrate to the stacked `.over(symbol)` shape, because per-frame Polars is only 6.3x and the restructure is what buys 48x.

## 9. Bun for the API. Real but modest, and it is a developer-experience win, not a speed win.

The measured win is 0.060 ms per request out of a 40 ms round trip. If you want SvelteKit and the API sharing one runtime and one language, that is a legitimate reason. Do not tell yourself it is about speed.

# Where a different technology would be a mistake

**Rust, Go, Zig, C#, or C++ for the quant core.** The seductive one is the PyO3 hybrid, so here is the arithmetic that kills it: after vectorisation, the greeks chain costs 0.0141 ms of compute plus 0.032 ms irreducibly spent constructing 200 Python result dicts. A perfect batched Rust call gets you to about 0.033 ms. The total available win is **13 microseconds**, against a 20,000 to 80,000 microsecond round trip. What breaks: production HMM regime detection does not exist in Rust. The best candidate, `rhmm`, has 66 total downloads in its entire existence and was created in January 2026. `statrs` is a port of Math.NET's distributions, with no bootstrap CI, no Wilson score interval, no hypothesis tests. RustQuant has been stale since 2024-11-19 and its author says it is a free-time project. gonum has no HMM, no bootstrap, no Wilson bounds, and no vectorised expression syntax, so every audited formula becomes a hand-typed loop. Zig has no statistics ecosystem at all. Math.NET's last stable release was January 2021. You would hand-write Baum-Welch with log-space stability, Viterbi, Wilson bounds, bootstrap CIs and fractional differencing: exactly the class of code where 88 defects were just found, with no oracle to check against because the 852 tests do not port.

**Julia.** The only technically respectable candidate in this group, and still no. It would buy about 10 microseconds on the hot kernel. For linear algebra it calls the identical BLAS numpy calls, so there is nothing to win there at all. Julia's real edge is scalar loops with complex logic, and the correct fix for a scalar loop in this codebase is to make it an array operation, which costs an afternoon rather than a year. Revisit only if you need a genuinely non-vectorisable path-dependent simulation such as American exercise boundaries.

**Mojo.** Hit 1.0 on 2026-08-12, one day before this was written. The structural problem is not maturity, it is the interop model: Mojo's Python interop "uses the CPython runtime without modification", so calling numpy or scipy from Mojo runs at exactly CPython speed. Mojo cannot make your existing code faster by definition. A win requires rewriting kernels natively, and native Mojo has no `ndtr`, no hmmlearn, no statsmodels. The compiler is still proprietary, and Qualcomm acquired Modular in June 2026.

**PyPy.** Not merely unhelpful but structurally incompatible. There will be no PyPy 3.12, and its cpyext layer makes numpy and pandas C-extension calls *slower* than CPython. Your workload measured about 90% C-extension time, so PyPy would slow down the dominant fraction to speed up the minority.

**Codon and Cython.** Both strictly dominated by Numba, which targets the identical code (numeric loops over numpy arrays), delivers 263x measured on your supertrend loop, requires one decorator, and keeps every test running against unchanged Python source. Codon has no pandas and no scipy. Cython adds a build toolchain and removes the readable Python source that the adversarial audit was performed against.

**Free-threaded (no-GIL) Python.** You would pay a 6% single-thread penalty on macOS ARM64 to solve a contention problem you do not have. `ProcessPoolExecutor(10)` already gives you 679 ms to 128 ms, a 5.3x win, today, with no rebuild. What would break: hmmlearn, pytrends and friends have no guaranteed free-threaded wheels, and any C extension without `Py_mod_gil` silently re-enables the GIL anyway.

**kdb+ / q.** Free licensing now, so the cost objection is gone and the real one remains: q is a different language, not a different driver. You would discard all 852 tests to re-derive Black-Scholes, GEX, HMM, Wilson bounds and skew-aware Kelly, reintroducing every one of the 88 defects unprotected, to save about 36 ms on a backtest that nobody watches. Also note the community edition caps at 4 threads on your 11-core box and 8 simultaneous connections, which cuts directly against "background workers precompute everything".

**ClickHouse.** Published ClickBench puts self-hosted ClickHouse at 32.3 s where DuckDB is the number one open-source result. The thing you would install and babysit is slower on your data than the thing you can `pip install`. Sizing guidance is 4 CPU and 8 GB minimum on a box already running Postgres (962 MB measured), Python workers, Bun and a tunnel.

**QuestDB.** Its headline advantage is 4M rows per second ingest. You ingest roughly 0.5 rows per second. That is a 7,000,000x overshoot on the only axis it wins.

**TimescaleDB.** The closest call among the stores, because it is a Postgres extension so your drivers and tests survive. But continuous aggregates exist to incrementalise expensive rollups, and your rollup measures 195 ms in a background job on a 15-minute cadence. Revisit past roughly 100M rows. Also, do not run it on PostgreSQL 17.1, which shipped a breaking binary-interface change.

**Sync engines: Zero, ElectricSQL, PowerSync, Replicache.** These exist to make *writes* feel instant across *multiple concurrent clients* with optimistic mutations and conflict resolution. You have one user who writes almost nothing, over data that changes when cron fires. Measured: the `@rocicorp/zero` 1.8.0 client bundles to 98,255 bytes gzipped, 3.3x the entire SvelteKit dashboard app (29,975 bytes gzipped), and its local read cannot beat 0.4 ms because it reads the same browser storage a service worker does. What would break operationally: Zero needs `wal_level=logical`, a persistent replication slot and two more supervised daemons on your laptop, and a stalled slot bloats the WAL and can take Postgres down. Zero also does not sync Postgres views and does not support array columns, which collides with dashboard rows carrying `flags` arrays. Replicache was archived by its owner on 2026-06-10. ElectricSQL is the healthiest of them at 18,435 bytes gzipped and is the right tool *if* the requirement ever becomes "updates must appear on the phone without a refresh, sub-second, while the user is watching". It is not the requirement today.

**SQLite WASM / OPFS and Dexie in the browser.** SQLite WASM's own vendor writeup is mostly a hazard list: the official build needs COOP and COEP headers, `OPFSWriteAheadVFS` is Chrome only, Safari and Chrome incognito do not support OPFS at all, and Chrome incognito caps at 100 MB with "unexpected errors" past it. All of that to hold a dataset that gzips to 3.5 KB. Dexie costs 32,769 bytes gzipped, more than your whole app, to turn a 0.05 ms in-memory filter into a 0.8 ms indexed query. Both are backwards at this data size.

**Qwik, Solid, React, Astro.** Qwik 2 is still beta (last stable `@builder.io/qwik` is 1.20.0, 40,302 weekly downloads versus Svelte's 5.27M) and it optimises away hydration, which measures 0.9 ms here. SolidStart 2.0 is one week old and Solid and Svelte 5 are within single-digit percent of each other on the keyed js-framework-benchmark. React is 21x more popular and would ship a heavier runtime to solve a 0.9 ms problem. Astro's 9 KB result is achieved by shipping zero JavaScript, which is impossible for a sortable filterable table; it would also cost you SvelteKit's client-side router and hover preloading.

**Fastify.** Worth calling out because it is the default "fast" recommendation and it is measurably wrong here: at concurrency 8 and 64 on your hardware it **lost** to the Python stack (15,708 rps and p99 8 ms versus 19,421 rps and p99 5 ms).

**One methodology warning:** TechEmpower archived its benchmark repository on 2026-03-24 after 13 years, with no successor. Anyone quoting "current 2026 framework benchmarks" at you is almost certainly quoting an SEO content farm. That is why every number above was measured on your machine or traced to a primary source.

# The recommended stack, final

| Layer | Decision | Confirms or changes the plan |
|---|---|---|
| Quant compute language | Python with numpy, scipy, pandas, hmmlearn. No Rust, no Julia, no Mojo, no Go, no C++ rewrite. | **CONFIRMS** |
| Options hot paths (`modules/options.py`) | Vectorise. Replace the scalar `_cdf = norm.cdf` at line 44 with a `math.erf` scalar path and `scipy.special.ndtr` for arrays. Hoist the seed-42 RNG draw out of the `iterrows` loops. Replace the four `iterrows()` loops at lines 2480, 2509, 2546, 2574 with zipped `.to_numpy()` columns. | **CHANGES** |
| Monte Carlo PoP | Batch the draw, keep the 10,000 paths. Do **not** substitute the analytic closed form. | **CHANGES** |
| Python version | Upgrade off 3.9.6 (the version actually in `.venv-ci`, end of life October 2025) to 3.12 or 3.13. For support lifetime, not speed. | **CHANGES** |
| pandas | Keep. Upgrade to 3.0 eventually for Copy-on-Write correctness, not performance. Do not set `dtype_backend='pyarrow'` expecting the float64 hot path to speed up: it will not. | **CONFIRMS** |
| Polars | Not now. Trigger to revisit: universe above 5,000 tickers or a move to intraday bars. | **CONFIRMS** |
| Numba | Hold in reserve for the 11 genuinely sequential loops (`ta.py` 233, 287, 338, 353, 387, 402, 412; `options.py` 971, 2171, 2611, 2841). Measured 263x on the supertrend loop. Apply only when a profile demands it. | **CONFIRMS** |
| API framework and server | Litestar plus Granian plus msgspec. Measured 19,421 rps at concurrency 64 against a realistic peak under 50 rps: roughly 400x headroom. | **CONFIRMS** |
| API response headers | Brotli compression plus explicit `Cache-Control` on every JSON response. | **CHANGES** |
| Snapshot endpoint | Add an immutable versioned `/api/snapshot/<build_id>.json` plus a short-TTL `/api/version` pointer. | **CHANGES** |
| System of record | PostgreSQL 17, single source of truth, materialised views, indexed reads only in the request path. | **CONFIRMS** |
| Postgres config in ARCHITECTURE.md | `effective_io_concurrency = 200` makes PostgreSQL 17 refuse to start on macOS. Set it to **0**. Export `LC_ALL` or the postmaster aborts with "became multithreaded during startup". | **CHANGES** |
| Analytical and backtest queries | DuckDB in process via `postgres_scanner`, summoned per query, holding no persistent state. Never on the dashboard read path. | **CHANGES** |
| Parquet lake | Defer. Build it when live-scanning Postgres actually hurts, not on day one. | **CHANGES** |
| Shared `.duckdb` file as a store | Forbidden. A read-only handle from the API permanently locks out the ingest writer. Parquet with atomic `os.replace` is the only safe handoff. | **CONFIRMS** (for a reason the doc does not currently state) |
| ClickHouse, QuestDB, TimescaleDB, kdb+, SQLite | All rejected. | **CONFIRMS** |
| Frontend framework | SvelteKit 2.70 with Svelte 5. Measured at 29,975 bytes gzipped for a complete dashboard route including the router. | **CONFIRMS** |
| Frontend runtime | Bun. Justified on developer experience, one runtime and one language shared with the API. Not on speed. | **CONFIRMS** |
| Client data model | One snapshot loaded into an in-memory Svelte 5 rune store. All sorting, filtering and tab switching local. No IndexedDB, no Dexie, no TinyBase, no WASM SQLite. | **CHANGES** |
| Service worker | Add one. Cache-first on the immutable snapshot, network-first with a short timeout on the version pointer. Version the cache name off the build id. | **CHANGES** |
| Cloudflare | Add Cache Rules marking API JSON cacheable, set `max-age=15, stale-while-revalidate=300` on the version pointer, keep HTTP/3 on. | **CHANGES** |
| Navigation | Keep `data-sveltekit-preload-data="hover"` on. Add a Speculation Rules block. Preserve bfcache eligibility: no `unload` handlers, no `no-store` on HTML. | **CHANGES** (adds to a default that is already correct) |
| Sync engines (Zero, Electric, PowerSync, Replicache) | None. Revisit ElectricSQL only if the requirement becomes live push updates while the user watches. | **CONFIRMS** |
| Test suite | Keep all 852 tests. They are the reason every recommendation above is safe. Add `pytest -n auto`: measured 48.96 s to 22.82 s. | **CONFIRMS**, with the `-n auto` flag as a **CHANGE** |
| QuantLib | Optional Python import, later, when you want American exercise or a real calendar and day-count engine. Never as a C++ rewrite. | **CHANGES** (adds an optional dependency) |

# What to do differently starting tomorrow

Ordered by measured payoff per hour of effort.

1. **Swap the scalar normal CDF. One afternoon.** In `/Users/hasroon/cashflow-trader/modules/options.py`, lines 41 to 45 currently do `from scipy.stats import norm; _cdf = norm.cdf`. Define the scalar `_cdf` and `_pdf` from `math.erf` and `math.exp` instead, and keep `norm` imported for anything vectorised. Measured: 35.7x to 39x on the 200-strike chain, with max absolute deviation 0.000e+00 across all six greeks, verified independently twice. Do not use the existing Abramowitz and Stegun fallback at line 49 for this: `math.erf` is exact to double precision and just as fast. Run the 852 tests. They should be untouched.

2. **Hoist the RNG and vectorise the four chain loops. One day.** `Opt.covered_calls` and `cash_secured_puts` re-seed `np.random.default_rng(seed=42)` inside `iterrows`, so all 60 strikes redraw the identical 10,000 path array. Draw once per chain and broadcast. Then replace the `iterrows()` at lines 2480, 2509, 2546 and 2574 with zipped `.to_numpy()` columns and array math over the strike vector. Measured: 7.939 ms to 1.868 ms on 60 strikes and 18.06 ms to 0.295 ms on 200 strikes, both with max deviation 0.000e+00. Full chain goes from roughly 35 ms to under 1 ms.

3. **Add compression and cache headers to the API. Two hours.** Brotli on JSON responses (22,118 bytes to 4,043 bytes, saving 14.5 ms on LTE), plus `Cache-Control` on everything. This single afternoon is worth 240 times more than the entire language migration you were considering.

4. **Ship the versioned snapshot endpoint. Half a day.** Have the scheduled worker write `/api/snapshot/<build_id>.json` marked immutable, plus a `/api/version` pointer with `max-age=15, stale-while-revalidate=300`. Load the snapshot once into an in-memory Svelte store. Every sort, filter and tab switch becomes a 0.05 ms local operation instead of a 40 ms round trip.

5. **Add the service worker. Half a day.** Cache-first on the immutable snapshot, network-first with a short timeout on the pointer. Cold reload goes from 131 to 202 ms down to 0.4 ms. Version the cache name off the build id and call `skipWaiting` and `clients.claim` deliberately, because a stuck service worker is the one way this step can hurt you.

6. **Configure Cloudflare. One afternoon.** Two Cache Rules marking your API JSON eligible for cache with an Edge TTL override. Confirm HTTP/3 is on. After this the MacBook and the tunnel are off the critical path for every cached response.

7. **Add a Speculation Rules block and check bfcache eligibility. One hour.** SvelteKit's hover preloading is already on by default, so the main job is not turning it off, then adding one `<script type="speculationrules">` block and removing any `unload` handlers or `no-store` on HTML.

8. **Fix two lines in ARCHITECTURE.md. Ten minutes.** Set `effective_io_concurrency = 0`, because 200 makes PostgreSQL 17 refuse to start on macOS. Note the `LC_ALL` requirement. This will save you a confused evening.

9. **Add `pytest -n auto`. Fifteen minutes.** 48.96 s to 22.82 s, all 852 still green. Your edit-test loop is at least as much of the "fast" experience as p99 latency is.

10. **Upgrade off Python 3.9.6 and reconcile the baseline.** The brief says 3.12.13 on an M3 Pro with 11 cores and 18 GB; `.venv-ci` reports 3.9.6 and two specialists' probes reported an M4 with 10 cores and 16 GB. Budget single-digit percent from the interpreter bump, not a step change. Do it for the support lifetime and wheel availability, and so that future measurements mean something.

11. **Add DuckDB via `postgres_scanner` the next time a backtest annoys you.** `INSTALL postgres; ATTACH '<dsn>' AS pg (TYPE postgres, READ_ONLY)`, then run the scan against `pg.bars`. Measured 2,659.6 ms to 100.6 ms. No ETL, no second copy of the truth, no new server.

12. **Then stop optimising the backend and re-measure.** After steps 1 through 6 your server compute is under 1 ms, your database read is 0.135 ms, your cached interaction is 0.4 ms and your render is under 1 ms at 50 rows. At that point the only remaining latency is physics and Cloudflare, and the honest next question is not "which language" but "which of these screens still makes me wait, and why".