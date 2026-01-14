from AlgorithmImports import *
from QuantConnect.Indicators import ConnorsRelativeStrengthIndex

class MeanReversionStrategy(QCAlgorithm):

    def Initialize(self):
        self.SetStartDate(2023, 3, 1)
        self.SetCash(100000)
        
        # --- GESTIONE RISCHIO PROP FIRM ---
        self.max_positions = 5
        self.max_risk_per_trade = 2000  # Rischio massimo di perdita per trade (2%)
        
        # Limite di sicurezza per la leva (es. non investire più di 150k su un singolo trade anche se l'ATR è minuscolo)
        self.max_position_value_limit = 150000 
        
        self.UniverseSettings.Resolution = Resolution.Daily
        self.AddUniverse(self.CoarseSelectionFunction)
        
        self.data = {}

    def CoarseSelectionFunction(self, coarse):
        selected = [x for x in coarse if x.Price > 10 and x.HasFundamentalData]
        sorted_by_volume = sorted(selected, key=lambda x: x.DollarVolume, reverse=True)
        return [x.Symbol for x in sorted_by_volume[:100]]

    def OnSecuritiesChanged(self, changes):
        for security in changes.RemovedSecurities:
            symbol = security.Symbol
            self.Transactions.CancelOpenOrders(symbol)
            if symbol in self.data:
                if not self.Portfolio[symbol].Invested:
                    self.data.pop(symbol)

        for security in changes.AddedSecurities:
            symbol = security.Symbol
            if symbol not in self.data:
                self.data[symbol] = SymbolData(self, symbol)

    def OnData(self, data):
        open_orders_count = len([x for x in self.Transactions.GetOpenOrders() if x.Status != OrderStatus.Filled])
        invested_count = len([x for x in self.Portfolio if x.Value.Invested])
        total_active = invested_count + open_orders_count

        for symbol in list(self.data.keys()): 
            symbol_data = self.data[symbol]
            
            if not symbol_data.IsReady or not data.ContainsKey(symbol):
                continue

            # --- GESTIONE USCITA ---
            if self.Portfolio[symbol].Invested:
                symbol_data.ManageExit()
                continue
            
            # --- GESTIONE INGRESSO ---
            if len(self.Transactions.GetOpenOrders(symbol)) > 0:
                if not symbol_data.CheckSetupCondition():
                     self.Transactions.CancelOpenOrders(symbol)
                continue

            if total_active < self.max_positions:
                
                if symbol_data.CheckSetupCondition():
                    
                    limit_price = symbol_data.bb.LowerBand.Current.Value * 0.995
                    
                    if limit_price < symbol_data.sma200.Current.Value:
                        continue
                    
                    # --- CALCOLO SIZE BASATO SUL RISCHIO ($2000) ---
                    atr_value = symbol_data.atr.Current.Value
                    
                    # La distanza dello stop loss è 3 volte l'ATR
                    stop_distance = atr_value * 3.0
                    
                    # Evitiamo divisioni per zero se ATR è nullo (raro ma possibile)
                    if stop_distance <= 0:
                        continue

                    # FORMULA MAGICA: Rischio / Distanza Stop
                    # Esempio: Rischio 2000$ / Stop Distanza 5$ = 400 Azioni
                    qty = int(self.max_risk_per_trade / stop_distance)
                    
                    # --- CONTROLLO LEVA Eccessiva ---
                    # Calcoliamo quanto staremmo spendendo
                    position_value = qty * limit_price
                    
                    # Se il calcolo ci dice di comprare 500k di roba perché l'ATR è basso,
                    # il broker ci bloccherebbe. Mettiamo un tetto (es. 1.5x leva sul capitale nominale)
                    if position_value > self.max_position_value_limit:
                        qty = int(self.max_position_value_limit / limit_price)
                    
                    if qty > 0:
                        self.LimitOrder(symbol, qty, limit_price)
                        total_active += 1

class SymbolData:
    def __init__(self, algorithm, symbol):
        self.algo = algorithm
        self.symbol = symbol
        
        self.crsi = ConnorsRelativeStrengthIndex(3, 2, 100)
        self.algo.RegisterIndicator(symbol, self.crsi, Resolution.Daily)
        
        self.sma200 = self.algo.SMA(symbol, 200, Resolution.Daily)
        self.sma50 = self.algo.SMA(symbol, 50, Resolution.Daily)
        self.bb = self.algo.BB(symbol, 20, 2, MovingAverageType.Simple, Resolution.Daily)
        self.atr = self.algo.ATR(symbol, 14, MovingAverageType.Simple, Resolution.Daily)
        
        self.entry_time = None
        
    @property
    def IsReady(self):
        return (self.sma200.IsReady and self.sma50.IsReady and 
                self.bb.IsReady and self.atr.IsReady and self.crsi.IsReady)

    def CheckSetupCondition(self):
        price = self.algo.Securities[self.symbol].Price
        
        sma200 = self.sma200.Current.Value
        sma50 = self.sma50.Current.Value
        lower_band = self.bb.LowerBand.Current.Value
        crsi_val = self.crsi.Current.Value
        
        trend_ok = (sma50 > sma200) and (sma50 > price) and (price > sma200)
        price_trigger = price <= lower_band
        crsi_trigger = crsi_val < 15
        
        return trend_ok and price_trigger and crsi_trigger

    def ManageExit(self):
        if self.entry_time is None:
            self.entry_time = self.algo.Time
            
        price = self.algo.Securities[self.symbol].Price
        avg_price = self.algo.Portfolio[self.symbol].AveragePrice
        days_in_trade = (self.algo.Time - self.entry_time).days
        
        target_price = self.bb.MiddleBand.Current.Value
        
        # TP
        if price >= target_price:
            self.algo.Liquidate(self.symbol, "TP: Middle Band")
            self.entry_time = None
            return

        # Time Stop
        if days_in_trade >= 8:
            self.algo.Liquidate(self.symbol, "Time Stop: 8 Days")
            self.entry_time = None
            return
            
        # Hard Stop (Questo è quello che protegge i tuoi 2000$)
        stop_price = avg_price - (self.atr.Current.Value * 3.0)
        if price < stop_price:
            self.algo.Liquidate(self.symbol, "Hard Stop: 3 ATR")
            self.entry_time = None
            return
