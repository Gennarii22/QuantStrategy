from AlgorithmImports import *
from QuantConnect.Indicators import AverageDirectionalIndex

class HolyGrailStrategy(QCAlgorithm):

    def Initialize(self):
        self.SetStartDate(2020, 1, 1)
        self.SetEndDate(2025, 10, 30)
        self.SetCash(100000)
        
        # PARAMETRI
        self.max_positions = 5
        self.risk_per_trade = 1000 
        
        # Universo: Top 50 Liquidità (Senza filtro fondamentali per includere ETF)
        self.UniverseSettings.Resolution = Resolution.Daily
        self.AddUniverse(self.CoarseSelectionFunction)
        
        self.data = {}

    def CoarseSelectionFunction(self, coarse):
        # FIX 2: Rimosso 'HasFundamentalData' per includere ETF (SPY, QQQ)
        selected = [x for x in coarse if x.Price > 20]
        sorted_by_volume = sorted(selected, key=lambda x: x.DollarVolume, reverse=True)
        return [x.Symbol for x in sorted_by_volume[:50]]

    def OnSecuritiesChanged(self, changes):
        for security in changes.RemovedSecurities:
            symbol = security.Symbol
            
            # Annulla ordini pendenti se il titolo esce
            self.Transactions.CancelOpenOrders(symbol)
            
            # FIX 1 (Zombie Fix): Rimuovi i dati SOLO se NON siamo investiti.
            # Se siamo investiti, dobbiamo mantenere i dati per gestire l'uscita!
            if symbol in self.data:
                if not self.Portfolio[symbol].Invested:
                    self.data.pop(symbol)
                else:
                    # Se siamo investiti, logghiamo che è uscito dall'universo ma lo teniamo d'occhio
                    # self.Debug(f"{symbol} uscito dall'universo ma mantenuto per gestione exit.")
                    pass

        for security in changes.AddedSecurities:
            if security.Symbol not in self.data:
                self.data[security.Symbol] = SymbolData(self, security.Symbol)

    def OnData(self, data):
        open_orders_count = len([x for x in self.Transactions.GetOpenOrders() if x.Status != OrderStatus.Filled])
        invested_count = len([x for x in self.Portfolio if x.Value.Invested])
        total_active = invested_count + open_orders_count

        # Cicliamo su una copia delle chiavi per sicurezza
        for symbol in list(self.data.keys()): 
            symbol_data = self.data[symbol]
            
            # Se il dato non c'è oggi (magari delistato o dati mancanti), salta
            if not data.ContainsKey(symbol):
                continue
                
            # Se gli indicatori non sono pronti (es. primi 20 giorni), salta
            if not symbol_data.IsReady:
                continue

            # --- GESTIONE USCITA ---
            # Deve avvenire PRIMA di rimuovere eventuali dati zombie
            if self.Portfolio[symbol].Invested:
                symbol_data.ManageExit()
                
                # Se abbiamo appena chiuso la posizione E il titolo non è più nell'universo attivo
                # possiamo finalmente rimuoverlo dalla memoria
                if not self.Portfolio[symbol].Invested and not self.UniverseManager.ActiveSecurities.ContainsKey(symbol):
                    self.data.pop(symbol)
                continue
            
            # --- GESTIONE INGRESSO ---
            # Solo se il titolo è ATTIVO nell'universo (non zombie)
            if not self.UniverseManager.ActiveSecurities.ContainsKey(symbol):
                continue

            open_orders = self.Transactions.GetOpenOrders(symbol)
            if len(open_orders) > 0:
                self.Transactions.CancelOpenOrders(symbol)
            
            if total_active < self.max_positions:
                
                if symbol_data.CheckSignal():
                    high_yesterday = symbol_data.daily_bar.High
                    buy_stop_price = high_yesterday + 0.05
                    low_yesterday = symbol_data.daily_bar.Low
                    stop_loss_price = low_yesterday - 0.05
                    
                    stop_distance = buy_stop_price - stop_loss_price
                    if stop_distance < (buy_stop_price * 0.01): 
                         stop_loss_price = buy_stop_price * 0.98
                         stop_distance = buy_stop_price - stop_loss_price

                    if stop_distance > 0:
                        qty = int(self.risk_per_trade / stop_distance)
                        if qty * buy_stop_price > 25000:
                            qty = int(25000 / buy_stop_price)

                        if qty > 0:
                            self.StopMarketOrder(symbol, qty, buy_stop_price)
                            symbol_data.pending_stop_price = stop_loss_price
                            total_active += 1

class SymbolData:
    def __init__(self, algorithm, symbol):
        self.algo = algorithm
        self.symbol = symbol
        self.adx = self.algo.ADX(symbol, 14, Resolution.Daily)
        self.ema20 = self.algo.EMA(symbol, 20, Resolution.Daily)
        self.window = RollingWindow[TradeBar](2)
        self.algo.Consolidate(symbol, Resolution.Daily, self.OnDailyBar)
        self.daily_bar = None
        self.pending_stop_price = 0

    def OnDailyBar(self, bar):
        self.window.Add(bar)
        self.daily_bar = bar

    @property
    def IsReady(self):
        return self.adx.IsReady and self.ema20.IsReady and self.window.IsReady

    def CheckSignal(self):
        if not self.window.IsReady: return False
        bar = self.window[0]
        ema = self.ema20.Current.Value
        adx = self.adx.Current.Value
        
        # REGOLA 1: Trend Forte
        if adx < 30: return False
            
        # REGOLA 2: Ritracciamento sulla EMA 20
        touched_ema = (bar.Low <= ema <= bar.High) or (abs(bar.Low - ema) / ema < 0.005)
        
        # REGOLA 3: Trend UP (filtro base)
        plus_di = self.adx.PositiveDirectionalIndex.Current.Value
        minus_di = self.adx.NegativeDirectionalIndex.Current.Value
        uptrend = plus_di > minus_di
        
        return touched_ema and uptrend

    def ManageExit(self):
        price = self.algo.Securities[self.symbol].Price
        avg_price = self.algo.Portfolio[self.symbol].AveragePrice
        
        if self.pending_stop_price > 0:
            hard_stop = self.pending_stop_price
        else:
            hard_stop = avg_price * 0.95
            
        ema_stop = self.ema20.Current.Value
        
        # Trailing Stop sulla EMA 20
        exit_trigger = max(hard_stop, ema_stop * 0.98)
        
        if price < exit_trigger:
            self.algo.Liquidate(self.symbol, "Exit: Trailing/Stop")
            self.pending_stop_price = 0
