from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "NM Finance"
    environment: str = "development"
    secret_key: str = "change-me-in-production-use-long-random-string"
    access_token_expire_minutes: int = 60 * 24
    refresh_token_expire_days: int = 30
    algorithm: str = "HS256"

    database_url: str = "postgresql+psycopg2://fiidesk:fiidesk@localhost:5432/fiidesk"
    db_pool_recycle_seconds: int = 1800
    redis_url: str = "redis://localhost:6379/0"

    cors_origins: str = "*"
    market_provider_url: str = ""
    news_feed_url: str = "https://news.google.com/rss/search?q=FII+OR+fundos+imobiliarios&hl=pt-BR&gl=BR&ceid=BR:pt-419"
    fcm_server_key: str = ""
    # Firebase Cloud Messaging HTTP v1 (service account) — preferred over legacy server key
    fcm_project_id: str = ""
    fcm_service_account_json: str = ""  # JSON string or path to a service account file
    # Deprecated: Termux agent push (prefer in-app NM Finance notifications)
    android_agent_url: str = ""
    android_agent_token: str = ""
    suggestion_score_threshold: float = 70.0
    suggestion_ttl_hours: int = 48
    invite_ttl_days: int = 7
    worker_interval_seconds: int = 300
    bdr_withholding_rate: float = 0.30
    llm_api_key: str = ""
    llm_api_base: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_local_base: str = "http://127.0.0.1:11434/v1"
    llm_local_model: str = "qwen2.5:7b"
    llm_local_key: str = "ollama"
    llm_prefer_local: bool = True
    llm_cloud_on_escalate: bool = True
    llm_timeout_seconds: float = 45.0
    llm_groq_429_cooldown_seconds: int = 15 * 60
    llm_local_keep_alive: str = "30m"
    news_classify_limit: int = 20

    # Swing Desk / brapi (never commit the token; put BRAPI_TOKEN in .env)
    brapi_token: str = ""
    brapi_base_url: str = "https://brapi.dev/api"
    swing_enabled: bool = True
    # ~4 refreshes/day on trading days; worker still loops on income interval
    swing_min_interval_seconds: int = 6 * 60 * 60
    swing_ohlc_ttl_seconds: int = 5 * 60 * 60
    swing_cache_dir: str = ".cache/brapi"
    swing_top_n: int = 10
    swing_suggestion_ttl_hours: int = 36
    swing_h1_enabled: bool = True
    swing_h1_ttl_seconds: int = 90 * 60

    # tastytrade Open API (única corretora/feed de cotações USD)
    tastytrade_client_id: str = ""
    tastytrade_client_secret: str = ""
    tastytrade_refresh_token: str = ""
    tastytrade_account_number: str = ""
    tastytrade_sandbox: bool = True
    tastytrade_base_url: str = "https://api.tastyworks.com"
    tastytrade_sandbox_base_url: str = "https://api.cert.tastyworks.com"
    tastytrade_oauth_scopes: str = "read trade openid"
    # tastytrade LIVE (produção, dinheiro real) — separado do sandbox/day-trade.
    # Credenciais de produção NÃO funcionam no sandbox e vice-versa (Context7).
    tastytrade_live_client_id: str = ""
    tastytrade_live_client_secret: str = ""
    tastytrade_live_refresh_token: str = ""
    tastytrade_live_account_number: str = ""
    # Account Streamer (OAuth, not DXLink quote token). Fill events enqueue reconcile.
    tastytrade_account_streamer_enabled: bool = True
    hv_dip_enabled: bool = True
    hv_dip_min_interval_seconds: int = 1800
    hv_dip_ohlc_ttl_seconds: int = 6 * 60 * 60
    hv_dip_cache_dir: str = ".cache/market"
    hv_dip_top_n: int = 10
    hv_dip_suggestion_ttl_hours: int = 36
    # Obsolete: only consumed by the legacy `scripts/hv_dip_backtest.py`.
    # Live entry uses `hv_dip_min_dip_pct` (or the learn-loop `dip_pct` config).
    # Kept so existing .env keys do not explode pydantic validation.
    hv_dip_dip_pct: float = 8.0
    hv_dip_min_dip_pct: float = 12.0
    hv_dip_lookback: int = 10
    hv_dip_hard_stop_pct: float = 12.0
    hv_dip_live_refresh_interval_seconds: int = 300
    hv_dip_live_min_dip_pct: float = 6.0
    hv_dip_approve_slippage_pct: float = 0.5
    hv_dip_exit_trailing_giveback_pct: float = 20.0
    hv_dip_exit_recovery_enabled: bool = True
    # Exit Engine V2 (LATCHED / PROTECT / time review)
    hv_dip_exit_v2_enabled: bool = True
    hv_dip_auto_close_enabled: bool = True
    hv_dip_latch_pct: float = 5.0
    # Trailing protect: giveback scales down as the peak grows (ramp), and widens
    # when the asset is recovering with room to the recent high.
    hv_dip_giveback_max: float = 0.50
    hv_dip_giveback_min: float = 0.20
    hv_dip_giveback_floor_pct: float = 25.0
    hv_dip_recovery_slack: float = 0.50
    # Opportunity scaling: deeper dips get a bigger target and more capital.
    hv_dip_target_recovery_share: float = 0.50
    hv_dip_target_max_pct: float = 50.0
    hv_dip_dip_alloc_max_mult: float = 2.0
    hv_dip_dip_alloc_full_at_pct: float = 30.0
    # Auto-buy: deep dip OR news catalyst, dip-scaled size, daily cash cap.
    hv_dip_auto_buy_enabled: bool = False
    hv_dip_auto_buy_min_dip_pct: float = 15.0
    hv_dip_auto_buy_daily_cash_pct: float = 50.0
    # Live USD: shadow records desk_decisions; auto-buy stays off until the
    # live_promotion checklist is green and this flag is flipped by hand.
    hv_dip_live_shadow: bool = True
    hv_dip_live_auto_buy: bool = False
    hv_dip_live_size_mult: float = 0.5
    hv_dip_max_hold_days: int = 14
    hv_dip_review_extension_days: int = 3
    # Quick Target exit (replaces 2R/50% target + LATCHED/PROTECT/giveback):
    # small positive target + hard stop + time-stop. Values are set by the
    # Phase 5 walk-forward sweep; these are the starting defaults.
    hv_dip_qt_target_r: float = 1.0
    hv_dip_qt_stop_pct: float = 5.0
    hv_dip_qt_max_hold_days: int = 3
    # Frozen calendar time-stop. Off by default: the desk exits on price action
    # (stop/target/giveback) and thesis, not on a deadline. The desk decides how
    # long to hold — no frozen days. Set True to restore the 3-day market sell.
    hv_dip_qt_time_stop_enabled: bool = False
    # Quick Target entry: whole-lot universe (max price) + equal-risk sizing
    # (risk budget = settled_cash × risk_pct). Values swept by Phase 5 backtest.
    hv_dip_qt_max_price: float = 20.0
    hv_dip_qt_risk_pct: float = 1.0
    # T+2 settlement (US cash account): sell proceeds are un-spendable for this
    # many business days. Guards the buy side against Good Faith Violations.
    hv_dip_settlement_days: int = 2
    # Scale-in (tranches): raised from 3 to 5 so the bot can keep averaging into
    # a quality name on repeated deep dips (tranche N+1 via "comprar mais" too).
    hv_dip_max_tranches: int = 5
    hv_dip_rotation_score_delta: float = 10.0
    # Quality / oscillation / mean-reversion (strategy alignment)
    hv_dip_min_dollar_volume: float = 20_000_000.0
    hv_dip_mega_dollar_volume: float = 200_000_000.0
    hv_dip_quality_bonus: float = 5.0
    hv_dip_min_recovery_rate: float = 0.6
    hv_dip_osc_swing_pct: float = 8.0
    hv_dip_osc_window: int = 84
    hv_dip_reject_fresh_high: bool = True
    # Structural-decline observation (Fase 5b)
    hv_dip_obs_recovery_min_pct: float = 5.0
    hv_dip_obs_probability_min: float = 0.6
    hv_dip_obs_risky_size_mult: float = 0.5
    # hv_dip learn loop (walk-forward auto-tuning; Fase 6b)
    hv_dip_learn_enabled: bool = True
    hv_dip_learn_interval_seconds: int = 24 * 60 * 60
    hv_dip_min_closed_signals: int = 30
    hv_dip_learn_significance: float = 0.05
    hv_dip_learn_min_margin_pct: float = 5.0
    hv_dip_learn_circuit_breaker_r: float = -0.3
    # Desk P&L goals (report / chart)
    desk_daily_pnl_target_pct: float = 7.0
    # P&L milestone notifications (loss/gain, USD accounts) — comma-separated values.
    pnl_milestones_enabled: bool = True
    pnl_milestones_usd: str = "2.5,5.0,7.5,10.0"
    # Reconciliation anomaly: alert when an order is stuck in `submitted` this long.
    order_stuck_alert_hours: float = 2.0
    # Paper/sandbox orders stuck in `submitted` longer than this are cancelled
    # (best-effort at the broker) and freed so rotation can re-buy. Day-TIF limit
    # buys are dead after one session anyway. Live orders are never auto-expired
    # (alert only) so real money can't double-buy on a token/auth gap.
    order_stuck_expire_hours: float = 20.0
    desk_stretch_equity_target: float = 130.0
    desk_stretch_avg_return_pct: float = 11.0
    desk_stretch_realized_pnl_target: float = 25.0
    desk_stretch_latched_pct: float = 55.0
    desk_stretch_protect_or_2r_pct: float = 40.0
    desk_stretch_expectancy_r: float = 0.45
    desk_stretch_max_drawdown_pct: float = 12.0
    desk_stretch_win_rate_pct: float = 58.0
    desk_stretch_horizon_trades: int = 40
    desk_stretch_horizon_days: int = 60
    # Password reset: echo code in API response only for local lab (never on shared hosts)
    password_reset_echo: bool = False
    password_reset_ttl_minutes: int = 15

    # Day trade study (US intraday observer — paper only, no auto orders)
    day_trade_enabled: bool = False
    day_trade_watchlist: str = "SPY,LCID,SNAP,XPEV,AMD,NET,BA,MARA"
    day_trade_candle_period: str = "5m"
    day_trade_streamer_enabled: bool = True
    day_trade_cache_dir: str = ".cache/day_trade"
    # Day trade learn loop (walk-forward auto-tuning)
    day_trade_learn_enabled: bool = True
    day_trade_learn_interval_seconds: int = 24 * 60 * 60
    day_trade_backfill_days: int = 5
    # Guardrails (anti-overfitting / anti-error)
    day_trade_min_closed_signals: int = 30
    day_trade_min_significance: float = 0.05
    day_trade_tune_min_margin_pct: float = 5.0
    day_trade_circuit_breaker_expectancy_r: float = -0.3
    # Risk / gating / regime
    day_trade_max_concurrent_signals: int = 6
    day_trade_daily_loss_limit_r: float = 5.0
    day_trade_session_min_minutes: int = 5
    day_trade_session_max_minutes: int = 360
    day_trade_lunch_skip: bool = True
    day_trade_gate_min_n: int = 10
    day_trade_regime_lookback: int = 10
    day_trade_regime_hysteresis_bars: int = 3
    day_trade_regime_slope_threshold: float = 0.01

    # NM News catalyst (Finnhub; never commit the key — put FINNHUB_API_KEY in .env)
    finnhub_api_key: str = ""
    finnhub_base_url: str = "https://finnhub.io/api/v1"
    news_us_enabled: bool = True
    news_confidence_min: float = 0.15
    news_event_whitelist: str = "partnership,guidance_up,upgrade,m_and_a,contract,product_launch"
    news_gap_filter_pct: float = 5.0
    news_window_hours: int = 12
    news_auto_buy_enabled: bool = False
    news_max_news_positions: int = 2
    news_score_bonus: float = 5.0
    # Neutral verdicts are graded against a volatility-scaled band instead of a
    # flat 1%: hv_dip selects high-volatility names by construction, so a fixed
    # band fails a third of the sample automatically.
    news_neutral_atr_mult: float = 0.5
    news_calibrate_batch: int = 400
    news_min_dollar_volume: float = 20_000_000.0
    news_min_price: float = 5.0

    # Index Core (DCA autonomo de indice, paper-first). Nao depende de opcoes
    # nem de stock-picking; converte o "buy & hold do indice" (o unico caminho
    # com expectancia positiva documentada para capital < US$ 500) em acumulacao
    # automatica. Default desligado — nada roda ate o deploy explicito.
    index_core_enabled: bool = False
    index_core_account_id: str = ""  # vazio = auto-pick 1a conta USD tastytrade
    index_core_tickers: str = "QQQ"  # so QQQ para perfil agressivo (ou "QQQ,SPY")
    index_core_weekly_usd: float = 50.0  # aporte por ticker por semana
    index_core_interval_seconds: int = 604800  # 7 dias
    index_core_regime_guard: bool = True  # pula aporte se QQQ < SMA200

    # Premium wheel (Fase B — venda de opcoes, condicionada). SKELETON ONLY:
    # nada roda ate conta live aprovada na Tastytrade + opcoes habilitadas +
    # capital >= minimo. Os parametros de selecao (delta/DTE/strike) ainda
    # precisam de walk-forward, como o Quick Target precisou. Default desligado.
    premium_enabled: bool = False
    premium_account_id: str = ""  # vazio = auto-pick 1a conta USD tastytrade live
    premium_min_capital_usd: float = 1000.0  # capital minimo para a Roda
    premium_tickers: str = "QQQ,SPY"  # underlyings liquidos
    premium_max_delta: float = 0.30  # delta maximo do put vendido (placeholder)
    premium_dte_min: int = 21  # days-to-expiry minimo (placeholder)
    premium_dte_max: int = 45  # days-to-expiry maximo (placeholder)
    premium_min_premium_usd: float = 20.0  # premio minimo/contrato (placeholder)
    premium_interval_seconds: int = 604800  # 7 dias

    # Mega Rotation (Fase C): caixa unico rotacionando entre mega-caps liquidas.
    # Compra o alvo mais descontado (maior queda da maxima recente), segura
    # enquanto valoriza, vende no trailing stop quando comeca a cair e gira o
    # caixa imediatamente para o proximo alvo. Paper-first, desligado por padrao.
    # Parametros escolhidos por walk-forward (valores iniciais; DEEPEN LATER).
    mega_rotation_enabled: bool = False
    mega_rotation_account_id: str = ""  # vazio = auto-pick 1a conta USD tastytrade
    mega_rotation_tickers: str = "AAPL,MSFT,NVDA,AMZN,GOOGL,META"  # mega-caps liquidas
    mega_rotation_dip_pct: float = 5.0  # queda minima da maxima recente para entrar
    mega_rotation_giveback_pct: float = 3.0  # trailing stop: vende apos cair X% do pico
    mega_rotation_lookback: int = 20  # janela (pregões) da "maxima recente"
    mega_rotation_confirm: bool = False  # True = exige virada para cima antes de entrar
    mega_rotation_position_usd: float = 25.0  # notional fixo por posicao (paper)
    mega_rotation_interval_seconds: int = 300  # reavalia a cada 5 min em pregao

    # Desk gate (capital orchestrator). Enforce only on USD paper; live/BRL skip.
    desk_gate_enabled: bool = True
    desk_gate_enforce: bool = True
    desk_gate_queue_enabled: bool = True
    desk_gate_usd_budgets: str = "hv_dip=0.4,index_core=0.4,mega_rotation=0"
    desk_gate_window_seconds: int = 300
    desk_gate_protect_enabled: bool = True
    desk_gate_cooldown_hours: float = 24.0
    desk_gate_stoploss_lookback_hours: float = 24.0
    desk_gate_stoploss_limit: int = 4
    desk_gate_max_drawdown_pct: float = 20.0
    desk_gate_low_profit_min_trades: int = 2
    desk_gate_regime_lock: bool = True
    desk_gate_regime_fail_closed: bool = True
    desk_gate_regime_ticker: str = "SPY"
    desk_gate_learn_enabled: bool = True
    desk_gate_learn_interval_seconds: int = 24 * 60 * 60
    desk_gate_learn_min_closed: int = 30
    # Refuse auto-execution when a source's resolved Brier is worse than chance.
    # Sources with too few resolved forecasts are left alone so paper can learn.
    desk_gate_calibration_enabled: bool = True
    desk_gate_calibration_max_brier: float = 0.30
    desk_gate_calibration_min_resolved: int = 30
    # A single populated bucket whose |p_mean - freq| exceeds this is enough to
    # deny, even when the average Brier still looks acceptable. Sparse buckets
    # (n below min_bucket_n) are ignored: one sample is not a reliability curve.
    # scikit-learn: isotonic overfits well below 1000 samples; we stay on Platt
    # plus this per-bucket gap check (Context7 / sklearn calibration).
    desk_gate_calibration_max_bucket_gap: float = 0.25
    desk_gate_calibration_min_bucket_n: int = 8
    # Judgment layer: numeric gates are priors. Can resize to 1 share (courage)
    # or refuse a scandal dump (observe). Kill-switch / paused still hard-stop.
    desk_judgment_enabled: bool = True
    # Study guards (deep_dip / breakout_h1) annotate instead of hard-block. The
    # desk decides from evidence: a refuted pattern becomes a note that travels
    # with the trade, not a lock. Set False to restore the old suppress mode.
    desk_studies_advisory: bool = True

    # Evolving memory + isolated research worker.
    learn_memory_path: str = ".cache/fiidesk/memory.db"
    learn_embedding_model: str = "nomic-embed-text"
    learn_embedding_dims: int = 256
    learn_research_budget_seconds: float = 45.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
