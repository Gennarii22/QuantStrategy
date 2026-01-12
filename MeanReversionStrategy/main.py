from AlgorithmImports import *
from QuantConnect.Indicators import ConnorsRelativeStrengthIndex

class MeanReversionStrategy(QCAlgorithm):

    def Initialize(self):
        self.SetStartDate(2023, 3, 1)  # Imposta data inizio
        self.SetCash(100000) # Imposta budget
        
        # PARAMETRI DI GESTIONE
        self.max_positions = 5  # Posizioni Massime
        self.risk_per_trade = 0.01 # Rischio trade
        
        # UNIVERSE SELECTION DINAMICO
        self.UniverseSettings.Resolution = Resolution.DAILY
        self.AddUniverse(self.CoarseSelectionFunction)
        
        # Dizionario per gestire i dati dei singoli simboli
        self.data = {}

    def CoarseSelectionFunction(self, coarse):
        # 1. Filtra per Prezzo > 10
        # 2. Ordina per DollarVolume decrescente (Liquidità)
        # 3. Prendi i primi 50
        selected = [x for x in coarse if x.Price > 10 and x.HasFundamentalData]
        sorted_by_volume = sorted(selected, key=lambda x: x.DollarVolume, reverse=True)
        return [x.Symbol for x in sorted_by_volume[:200]]

    def OnSecuritiesChanged(self, changes):
        # Rimuove dati di titoli usciti dall'universo
        for security in changes.RemovedSecurities:
            symbol = security.Symbol
            if symbol in self.data and not self.Portfolio[symbol].Invested: #se l'azione non è in portfolio 
                # Pulizia indicatori se necessario o semplice rimozione dal dict
                self.data.pop(symbol) #rimuove dall'elendo

        # Inizializza dati per nuovi titoli entrati nell'universo
        for security in changes.AddedSecurities:
            symbol = security.Symbol
            if symbol not in self.data:
                self.data[symbol] = SymbolData(self, symbol)

    def OnData(self, data):
        # Conta posizioni aperte
        invested_count = len([x for x in self.Portfolio if x.Value.Invested])

        # Scansiona tutti i simboli attivi nel dizionario dati
        for symbol in list(self.data.keys()): 
            symbol_data = self.data[symbol]
            
            # Se il dato non è pronto o il simbolo non è nei dati correnti, salta
            if not symbol_data.IsReady or not data.ContainsKey(symbol):
                continue

            # Se siamo già investiti in questo simbolo, NON fare nulla (niente pyramiding)
            if self.Portfolio[symbol].Invested:

                symbol_data.ManageExit(self.Portfolio[symbol])
                continue
            
            # LOGICA DI USCITA (Exit)
            # Gestita internamente alla logica o qui se hai posizioni aperte
            if invested_count < self.max_positions and not self.Portfolio[symbol].Invested:
                if symbol_data.CheckEntrySignal():

                    current_price = self.Securities[symbol].Price
                    atr_value = symbol_data.atr.Current.Value

                    stop_dist = atr_value * 3
                    
                    if stop_dist > 0:
                        risk_amount = 100000 * self.risk_per_trade
                        qty = int(risk_amount / stop_dist)

                        max_qty = round(float(10000 * 0.95 / current_price), 0)
                        qty = min(qty, max_qty)

                        if qty > 0:
                            self.MarketOrder(symbol, qty)
                            symbol_data.entry_day = self.Time
                            invested_count += 1

class SymbolData:
    def __init__(self, algorithm, symbol):
        self.algo = algorithm
        self.symbol = symbol
        
        # 1. Connors RSI (2, 2, 100)
        self.crsi = ConnorsRelativeStrengthIndex(2, 2, 100)
        self.algo.RegisterIndicator(symbol, self.crsi, Resolution.Daily)
        
        # 2. SMA 200
        self.sma200 = self.algo.SMA(symbol, 200, Resolution.Daily)
        
        # 3. SMA 5
        self.sma5 = self.algo.SMA(symbol, 5, Resolution.Daily)
        
        # 4. ATR (Fixed: using named argument for resolution)
        self.atr = self.algo.ATR(symbol, 14, resolution=Resolution.Daily)
        
        self.entry_day = -1
        
    @property
    def IsReady(self):
        return self.crsi.IsReady and self.sma200.IsReady and self.sma5.IsReady and self.atr.IsReady

    def CheckEntrySignal(self):
        price = self.algo.Securities[self.symbol].Price
        
        # Trend Filter: Price > SMA200
        if not self.sma200.IsReady or price < self.sma200.Current.Value:
            return False
            
        # Trigger: CRSI < 15
        if self.crsi.Current.Value < 15: 
            self.entry_day = self.algo.Time
            return True
            
        return False

    def ManageExit(self, position):
        price = self.algo.Securities[self.symbol].Price
        avg_price = position.AveragePrice
        
        # Stop Loss (2x ATR from current value approx)
        stop_loss_price = avg_price - (self.atr.Current.Value * 2.0)
        take_profit_price = avg_price + (self.atr.Current.Value * 3.0)
        
        if price < stop_loss_price:
            self.algo.Liquidate(self.symbol, "Stop Loss ATR")
            return

        # Exit SMA 5
        if price >= take_profit_price:
            self.algo.Liquidate(self.symbol, "Take Profit ATR")
            return
            
