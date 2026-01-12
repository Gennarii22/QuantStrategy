# QUANTCONNECT ALGORITHM - GPCS RESEARCH BOUTIQUE
# STRATEGY: 5-Minute ORB (Zarattini/Aziz Logic)
# ASSET: QQQ
# TIMEFRAME: 1 Minute data (consolidated to 5 min for setup)

from AlgorithmImports import *

class ZarattiniORB(QCAlgorithm):
    def Initialize(self):
        self.SetStartDate(2020, 1, 1)  # Data Inizio Backtest
        self.SetEndDate(2025, 1, 1)    # Data Fine Backtest
        self.SetCash(100000)           # Capitale $100k
        
        # Asset Selection (QQQ for Benchmark)
        self.symbol = self.AddEquity("QQQ", Resolution.Minute).Symbol
        
        # Parameters
        self.orb_period = 5 # 5 minuti opening range
        self.invested_today = False # Per fare un solo trade al giorno
        
        # Variables for High/Low of the first bar
        self.opening_high = 0
        self.opening_low = 0
        
        # Scheduled Events
        # 1. Reset variables at Market Open
        self.Schedule.On(self.DateRules.EveryDay(self.symbol), \
                         self.TimeRules.At(9, 30), \
                         self.ResetDaily)
        
        # 2. End of Day Exit (15:55 NY Time)
        self.Schedule.On(self.DateRules.EveryDay(self.symbol), \
                         self.TimeRules.At(15, 55), \
                         self.LiquidatePositions)

    def OnData(self, data):
        # Safety checks
        if not data.ContainsKey(self.symbol) or data[self.symbol] is None: return
        if self.invested_today: return
        
        # Orario Corrente (NY Time)
        current_time = self.Time
        
        # FASE 1: Registra il range nei primi 5 minuti (9:30 - 9:35)
        if current_time.hour == 9 and current_time.minute < 30 + self.orb_period:
            # Stiamo solo osservando, aggiorniamo mentalmente il range se necessario
            # In realtà su QC basta aspettare le 9:35 per guardare indietro
            pass

        # FASE 2: Alle 9:35 esatte, calcoliamo il range
        if current_time.hour == 9 and current_time.minute == 35:
            # Prende la history degli ultimi 5 minuti
            history = self.History(self.symbol, 5, Resolution.Minute)
            if not history.empty:
                self.opening_high = history['high'].max()
                self.opening_low = history['low'].min()
                # Debug (Glass Box Transparency)
                self.Log(f"ORB Setup: High {self.opening_high} / Low {self.opening_low}")

        # FASE 3: Trading (Dalle 9:36 alle 15:50)
        if current_time.hour >= 9 and current_time.minute > 35:
            price = data[self.symbol].Close
            
            # Entry Long
            if price > self.opening_high and self.opening_high > 0:
                self.SetHoldings(self.symbol, 1.0) # Investi 100% capitale
                self.invested_today = True
                self.Log(f"LONG ENTRY at {price}")
                
            # Entry Short
            elif price < self.opening_low and self.opening_low > 0:
                self.SetHoldings(self.symbol, -1.0) # Investi 100% capitale (Short)
                self.invested_today = True
                self.Log(f"SHORT ENTRY at {price}")

    def ResetDaily(self):
        self.invested_today = False
        self.opening_high = 0
        self.opening_low = 0

    def LiquidatePositions(self):
        self.Liquidate()
        self.Log("EOD Exit")
