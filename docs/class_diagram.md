# Diagramme de classes de CryptoAnalyzer

Ce document décrit la structure orientée objet de l’application de surveillance technique et d’alertes crypto.

## Vue d’ensemble

L’architecture suit une approche en couches :

- Couche d’accès aux données : récupération OHLCV depuis Binance
- Couche d’analyse : calcul des indicateurs techniques
- Couche de règles : evaluation des alertes
- Couche de présentation : génération de graphiques et notification Discord
- Couche d’orchestration : moteur principal qui relie l’ensemble

## Diagramme Mermaid

```mermaid
classDiagram
    class Symbol {
        +str value
        +__str__()
    }

    class Timeframe {
        +str value
        +str label
        +int candles_chart
        +__str__()
    }

    class OHLCVData {
        +Symbol symbol
        +Timeframe timeframe
        +DataFrame df
    }

    class Alert {
        +Symbol symbol
        +Timeframe timeframe
        +str rule_name
        +str message
        +datetime triggered_at
        +str severity
        +Optional~str~ chart_path
    }

    class IDataFetcher {
        <<interface>>
        +fetch(symbol, timeframe, limit) OHLCVData
    }

    class IIndicatorCalculator {
        <<interface>>
        +calculate(data) DataFrame
    }

    class IAlertRule {
        <<interface>>
        +name
        +evaluate(symbol, timeframe, enriched_df, params) Optional~Alert~
    }

    class INotifier {
        <<interface>>
        +send(alert)
        +send_chart(alert, chart_path)
    }

    class IChartGenerator {
        <<interface>>
        +generate(data, enriched_df, output_path) str
    }

    class IConfigLoader {
        <<interface>>
        +load() dict
    }

    class BinanceFetcher {
        -int timeout
        -int retry
        +fetch(symbol, timeframe, limit) OHLCVData
        -_resolve_interval(timeframe) str
        -_fetch_paginated(symbol, interval, limit) DataFrame
        -_fetch_single(symbol, interval, limit, end_time_ms) DataFrame
        -_get_with_retry(params) list
    }

    class TechnicalIndicatorCalculator {
        +calculate(data) DataFrame
        -_add_sma(df, period) DataFrame
        -_add_rsi(df, period) DataFrame
        -_add_macd(df, fast, slow, signal) DataFrame
        -_ema_series(series, period) list
        -_add_bollinger(df, period, std_dev) DataFrame
    }

    class ThresholdAlertRule {
        -str _name
        +name
        +evaluate(symbol, timeframe, enriched_df, params) Optional~Alert~
    }

    class AlertCondition {
        +Operand left
        +str operator_str
        +Operand right
        +str agg
        +Optional~str~ legacy_indicator
        +Optional~float~ threshold_pct
        +from_dict(config) AlertCondition
        +max_offset() int
        +is_legacy() bool
        +evaluate(df, lookback) tuple
    }

    class Operand {
        +Optional~str~ indicator
        +int offset
        +Optional~float~ value
        +from_dict(config) Operand
        +required_rows() int
        +resolve(df) Optional~float~
    }

    class AlertRuleRegistry {
        -dict _rules
        +register(rule_class, rule_name)
        +build(rule_name) IAlertRule
    }

    class AlertEngine {
        -IDataFetcher _fetcher
        -IIndicatorCalculator _calc
        -INotifier _notifier
        -IChartGenerator _charts
        -AlertRuleRegistry _registry
        -dict _config
        +run_daily() list~Alert~
        +run_hourly() list~Alert~
        -_process_symbol_timeframe(symbol, timeframe, lookback) list~Alert~
        -_generate_chart(data, enriched, alert) Optional~str~
        -_build_timeframes(daily) list~Timeframe~
    }

    class JsonConfigLoader {
        -Path _path
        +load() dict
        -_validate(config)
    }

    class DiscordNotifier {
        -str _webhook_url
        -str _username
        -Optional~str~ _avatar_url
        +send(alert)
        +send_chart(alert, chart_path)
        -_build_embed_payload(alert, with_image) dict
        -_post_json(payload)
        -_post_with_file(payload, chart_file)
        -_request_with_retry(method, payload, file_content, file_name)
    }

    class MatplotlibChartGenerator {
        -int _dpi
        -tuple _figsize
        +generate(data, enriched_df, output_path) str
        -_create_figure(title)
        -_plot_ohlcv(ax, df)
        -_plot_volume(ax, df)
        -_plot_macd(ax, df)
        -_plot_rsi(ax, df)
        -_format_xaxis(ax, df)
    }

    class NullNotifier {
        +send(alert)
        +send_chart(alert, chart_path)
    }

    class Runner {
        <<entry point>>
        +main()
        -_build_engine(config_path, no_notifier) AlertEngine
        +cmd_daily(args)
        +cmd_hourly(args)
        +cmd_chart(args)
    }

    IDataFetcher <|.. BinanceFetcher
    IIndicatorCalculator <|.. TechnicalIndicatorCalculator
    IAlertRule <|.. ThresholdAlertRule
    INotifier <|.. DiscordNotifier
    INotifier <|.. NullNotifier
    IChartGenerator <|.. MatplotlibChartGenerator
    IConfigLoader <|.. JsonConfigLoader

    AlertEngine --> IDataFetcher
    AlertEngine --> IIndicatorCalculator
    AlertEngine --> INotifier
    AlertEngine --> IChartGenerator
    AlertEngine --> AlertRuleRegistry
    AlertEngine --> Alert

    AlertRuleRegistry --> IAlertRule
    ThresholdAlertRule --> AlertCondition
    AlertCondition --> Operand
    ThresholdAlertRule --> Alert

    BinanceFetcher --> OHLCVData
    TechnicalIndicatorCalculator --> OHLCVData
    MatplotlibChartGenerator --> OHLCVData
    DiscordNotifier --> Alert

    Runner --> AlertEngine
    Runner --> JsonConfigLoader
    Runner --> BinanceFetcher
    Runner --> TechnicalIndicatorCalculator
    Runner --> MatplotlibChartGenerator
    Runner --> DiscordNotifier
    Runner --> NullNotifier

    Symbol <-- OHLCVData
    Timeframe <-- OHLCVData
    Symbol <-- Alert
    Timeframe <-- Alert
```

## Description des principaux composants

### 1. Modèle de domaine

- Symbol : représente une paire de crypto-monnaie
- Timeframe : représente une période de temps (1h, 1d, 1w)
- OHLCVData : contient les données brutes issues d’une source externe
- Alert : structure finale d’alerte générée par le moteur

### 2. Couche d’accès aux données

- BinanceFetcher : récupère les bougies OHLCV depuis l’API Binance

### 3. Couche d’analyse technique

- TechnicalIndicatorCalculator : enrichit les données avec SMAs, RSI, MACD et Bollinger

### 4. Couche de règles d’alerte

- ThresholdAlertRule : règle générique configurable
- AlertCondition : représente une condition logique d’alerte
- Operand : définit une valeur ou un indicateur à comparer
- AlertRuleRegistry : instancie les règles par nom

### 5. Couche de notification et graphique

- DiscordNotifier : envoie l’alerte sur Discord
- MatplotlibChartGenerator : produit un graphique PNG multi-panneaux

### 6. Orchestration

- AlertEngine : pilote le cycle complet : fetch → calcul → règles → notification
- Runner : point d’entrée CLI pour exécuter l’application en mode daily, hourly ou chart

## Résumé architectural

Le projet est construit autour d’un moteur central qui dépend d’abstractions plutôt que de classes concrètes. Cela permet de :

- remplacer facilement un fetcher ou un notifier
- ajouter de nouvelles règles sans modifier le moteur
- tester les composants indépendamment
