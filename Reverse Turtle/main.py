from AlgorithmImports import *

class ReverseTurtleSoupStrategy(QCAlgorithm):

    def Initialize(self):
        self.SetStartDate(2020, 1, 1)
        self.SetEndDate(2025, 10, 30)
        self.SetCash(100000)
        
        self.max_positions = 5
        self.risk_per_trade = 1500 
        self.lookback_days = 20
        
        self.UniverseSettings.Resolution = Resolution.Daily
        self.AddUniverse(self.CoarseSelectionFunction)
        
        self.data = {}

    def CoarseSelectionFunction(self, coarse):
        selected = [x for x in coarse if x.Price > 15 and x.HasFundamentalData]
        sorted_by_volume = sorted(selected, key=lambda x: x.DollarVolume, reverse=True)
        return [x.Symbol for x in sorted_by_volume[:50]]

    def OnSecuritiesChanged(self, changes):
        for security in changes.AddedSecurities:
            if security.Symbol not in self.data:
                self.data[security.Symbol] = SymbolData(self, security.Symbol, self.lookback_days)

    def OnData(self, data):
        invested_count = len([x for x in self.Portfolio if x.Value.Invested])
        
        for symbol in list(self.data.keys()): 
            symbol_data = self.data[symbol]
            
            if not symbol_data.IsReady or not data.ContainsKey(symbol):
                continue

            # GESTIONE USCITA (Automatica in base alla posizione aperta)
            if self.Portfolio[symbol].Invested:
                symbol_data.ManageExit()
                continue
            
            # GESTIONE INGRESSO (INVERTITA)
            if invested_count < self.max_positions:
                
                signal = symbol_data.CheckSignal()
                
                if signal != 0: 
                    
                    atr = symbol_data.atr.Current.Value
                    current_price = self.Securities[symbol].Price
                    stop_dist = atr * 1.5 
                    
                    # --- LOGICA INVERTITA ---
                    
                    # SEGNALE ORIGINALE 1 (Era LONG su falso minimo)
                    # ORA: Andiamo SHORT (Scommettiamo che il minimo si rompe di nuovo)
                    if signal == 1: 
                        entry_price = current_price
                        stop_loss = entry_price + stop_dist # Stop sopra
                        qty = int(self.risk_per_trade / stop_dist)
                        
                        if qty * entry_price > 30000: qty = int(30000 / entry_price)
                        
                        if qty > 0:
                            self.MarketOrder(symbol, -qty) # SELL
                            symbol_data.entry_day = self.Time
                            symbol_data.entry_price = entry_price
                            invested_count += 1
                            
                    # SEGNALE ORIGINALE -1 (Era SHORT su falso massimo)
                    # ORA: Andiamo LONG (Scommettiamo che il massimo si rompe di nuovo)
                    elif signal == -1: 
                        entry_price = current_price
                        stop_loss = entry_price - stop_dist # Stop sotto
                        qty = int(self.risk_per_trade / stop_dist)
                        
                        if qty * entry_price > 30000: qty = int(30000 / entry_price)
                        
                        if qty > 0:
                            self.MarketOrder(symbol, qty) # BUY
                            symbol_data.entry_day = self.Time
                            symbol_data.entry_price = entry_price
                            invested_count += 1

class SymbolData:
    def __init__(self, algorithm, symbol, lookback):
        self.algo = algorithm
        self.symbol = symbol
        self.lookback = lookback
        self.window = RollingWindow[TradeBar](lookback + 5)
        self.algo.Consolidate(symbol, Resolution.Daily, self.OnDailyBar)
        self.atr = self.algo.ATR(symbol, 14, MovingAverageType.Simple, Resolution.Daily)
        self.entry_day = None
        self.entry_price = 0

    def OnDailyBar(self, bar):
        self.window.Add(bar)

    @property
    def IsReady(self):
        return self.window.IsReady and self.atr.IsReady

    def CheckSignal(self):
        bar_today = self.window[0]
        lows = [self.window[i].Low for i in range(1, self.lookback + 1)]
        highs = [self.window[i].High for i in range(1, self.lookback + 1)]
        min_20 = min(lows)
        max_20 = max(highs)
        
        days_ago_min = lows.index(min_20) + 1 
        days_ago_max = highs.index(max_20) + 1
        
        if (days_ago_min >= 3):
            if (bar_today.Low < min_20) and (bar_today.Close > min_20):
                return 1 # Originale Long -> Ora Short
        
        if (days_ago_max >= 3):
            if (bar_today.High > max_20) and (bar_today.Close < max_20):
                return -1 # Originale Short -> Ora Long
                
        return 0

    def ManageExit(self):
        price = self.algo.Securities[self.symbol].Price
        qty = self.algo.Portfolio[self.symbol].Quantity
        days_in_trade = (self.algo.Time - self.entry_day).days
        
        # Time Stop
        if days_in_trade >= 3:
            self.algo.Liquidate(self.symbol, "Time Stop: 3 Days")
            return
            
        # SL / TP
        atr_val = self.atr.Current.Value
        
        if qty > 0: # Long
            stop_price = self.entry_price - (atr_val * 1.5)
            tp_price = self.entry_price + (atr_val * 2.0)
            if price < stop_price: self.algo.Liquidate(self.symbol, "Stop Loss")
            elif price > tp_price: self.algo.Liquidate(self.symbol, "Take Profit")
                
        elif qty < 0: # Short
            stop_price = self.entry_price + (atr_val * 1.5)
            tp_price = self.entry_price - (atr_val * 2.0)
            if price > stop_price: self.algo.Liquidate(self.symbol, "Stop Loss")
            elif price < tp_price: self.algo.Liquidate(self.symbol, "Take Profit")
