from AlgorithmImports import *
from QuantConnect.Indicators import ConnorsRelativeStrengthIndex

class MeanReversionStrategy(QCAlgorithm):

    def Initialize(self):
        self.SetStartDate(2023, 3, 1)
        self.SetCash(100000)
        
        # --- PARAMETRI ---
        self.max_positions = 5
        self.risk_per_trade = 0.02
        
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
            self.Transactions.CancelOpenOrders(symbol) # Cancella ordini pendenti su titoli rimossi
            if symbol in self.data:
                if not self.Portfolio[symbol].Invested:
                    self.data.pop(symbol)

        for security in changes.AddedSecurities:
            symbol = security.Symbol
            if symbol not in self.data:
                self.data[symbol] = SymbolData(self, symbol)

    def OnData(self, data):
        # Conta posizioni investite + ordini pendenti per evitare over-trading
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
            # Se abbiamo già un ordine pendente, controlliamo se è ancora valido
            if len(self.Transactions.GetOpenOrders(symbol)) > 0:
                if not symbol_data.CheckSetupCondition():
                     self.Transactions.CancelOpenOrders(symbol)
                continue

            # Nuovi ordini solo se abbiamo slot liberi
            if total_active < self.max_positions:
                
                # Setup: Trend + Bollinger + CRSI
                if symbol_data.CheckSetupCondition():
                    
                    # Prezzo Limit: 1% sotto la Lower Bollinger
                    limit_price = symbol_data.bb.LowerBand.Current.Value * 0.995
                    
                    # Controllo sicurezza: Non comprare se il limit price è SOTTO la SMA200 (trend rotto)
                    # Se vuoi rischiare di più, rimuovi questa riga
                    if limit_price < symbol_data.sma200.Current.Value:
                        continue
                    
                    # Size Position
                    cash_per_trade = self.Portfolio.TotalPortfolioValue / self.max_positions
                    qty = int(cash_per_trade / limit_price)
                    
                    if qty > 0:
                        self.LimitOrder(symbol, qty, limit_price)
                        total_active += 1 # Aggiorna contatore locale

class SymbolData:
    def __init__(self, algorithm, symbol):
        self.algo = algorithm
        self.symbol = symbol
        
        # 1. CRSI (Reintegrato)
        self.crsi = ConnorsRelativeStrengthIndex(3, 2, 100)
        self.algo.RegisterIndicator(symbol, self.crsi, Resolution.Daily)
        
        # 2. SMA 200 (Trend Lungo)
        self.sma200 = self.algo.SMA(symbol, 200, Resolution.Daily)
        
        # 3. SMA 50 (Trend Medio / Target)
        self.sma50 = self.algo.SMA(symbol, 50, Resolution.Daily)
        
        # 4. Bollinger Bands (20, 2)
        self.bb = self.algo.BB(symbol, 20, 2, MovingAverageType.Simple, Resolution.Daily)
        
        # 5. ATR (FIXED ERROR: Aggiunto MovingAverageType.Simple)
        self.atr = self.algo.ATR(symbol, 14, MovingAverageType.Simple, Resolution.Daily)
        
        self.entry_time = None
        
    @property
    def IsReady(self):
        return (self.sma200.IsReady and self.sma50.IsReady and 
                self.bb.IsReady and self.atr.IsReady and self.crsi.IsReady)

    def CheckSetupCondition(self):
        price = self.algo.Securities[self.symbol].Price
        
        # Indicator Values
        sma200 = self.sma200.Current.Value
        sma50 = self.sma50.Current.Value
        lower_band = self.bb.LowerBand.Current.Value
        crsi_val = self.crsi.Current.Value
        
        # 1. Trend Sandwich: SMA50 > Price > SMA200
        # Nota: L'ordine deve partire quando SMA50 > SMA200, ma il Price sta crollando.
        trend_ok = (sma50 > sma200) and (sma50 > price) and (price > sma200)
        
        # 2. Trigger Prezzo: Sotto Lower Bollinger
        price_trigger = price <= lower_band
        
        # 3. Trigger CRSI: Ipervenduto (Reintegrato)
        crsi_trigger = crsi_val < 15
        
        return trend_ok and price_trigger and crsi_trigger

    def ManageExit(self):
        if self.entry_time is None:
            self.entry_time = self.algo.Time
            
        price = self.algo.Securities[self.symbol].Price
        avg_price = self.algo.Portfolio[self.symbol].AveragePrice
        days_in_trade = (self.algo.Time - self.entry_time).days
        
        # MODIFICA 1: Target sulla Middle Band (SMA 20) invece che SMA 50
        # La Middle Band è self.bb.MiddleBand.Current.Value
        target_price = self.bb.MiddleBand.Current.Value
        
        if price >= target_price:
            self.algo.Liquidate(self.symbol, "TP: Middle Band")
            self.entry_time = None
            return

        # MODIFICA 2: Time Stop ridotto a 8 giorni (dato che il target è più vicino)
        if days_in_trade >= 8:
            self.algo.Liquidate(self.symbol, "Time Stop: 8 Days")
            self.entry_time = None
            return
            
        # Hard Stop resta uguale
        stop_price = avg_price - (self.atr.Current.Value * 3.0)
        if price < stop_price:
            self.algo.Liquidate(self.symbol, "Hard Stop: 3 ATR")
            self.entry_time = None
            return
