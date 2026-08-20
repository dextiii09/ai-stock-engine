import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, TrendingUp, AlertCircle, CheckCircle2, ChevronRight, Lock } from 'lucide-react';

interface TradeModalProps {
  isOpen: boolean;
  onClose: () => void;
  symbol: string;
  price: number;
}

export const TradeModal: React.FC<TradeModalProps> = ({ isOpen, onClose, symbol, price }) => {
  const [orderType, setOrderType] = useState<'Market' | 'Limit' | 'AI Execution'>('AI Execution');
  const [quantity, setQuantity] = useState('10');
  const [step, setStep] = useState<'Configuring' | 'Executing' | 'Success'>('Configuring');

  const totalValue = (parseFloat(quantity) || 0) * price;

  const handleExecute = () => {
    setStep('Executing');
    setTimeout(() => {
      setStep('Success');
      setTimeout(() => {
        onClose();
        setTimeout(() => setStep('Configuring'), 500); // reset after close
      }, 2000);
    }, 1500);
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <div className="fixed inset-0 z-[150] flex items-end sm:items-center justify-center p-4 sm:p-0">
          
          <motion.div 
            initial={{ opacity: 0 }} 
            animate={{ opacity: 1 }} 
            exit={{ opacity: 0 }} 
            onClick={onClose}
            className="absolute inset-0 bg-background/80 backdrop-blur-md"
          />

          <motion.div
            initial={{ opacity: 0, y: 100, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.95 }}
            className="relative w-full max-w-md bg-card border border-border shadow-2xl rounded-3xl overflow-hidden flex flex-col"
          >
            {/* Header */}
            <div className="px-6 py-4 flex items-center justify-between border-b border-border bg-background/50">
              <div>
                <h3 className="font-display font-bold text-xl flex items-center gap-2">
                  Trade {symbol}
                </h3>
                <p className="text-xs text-muted-foreground flex items-center gap-1">
                  Current Price: <span className="font-bold text-foreground">${price.toFixed(2)}</span>
                </p>
              </div>
              <button onClick={onClose} className="p-2 rounded-full hover:bg-border/50 text-muted-foreground transition-colors">
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Content */}
            <div className="p-6">
              
              {step === 'Configuring' && (
                <motion.div initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} className="space-y-6">
                  
                  {/* Order Type Toggle */}
                  <div className="flex bg-background border border-border rounded-xl p-1">
                    {['Market', 'Limit', 'AI Execution'].map((type) => (
                      <button 
                        key={type}
                        onClick={() => setOrderType(type as any)}
                        className={`flex-1 py-2 text-xs font-bold rounded-lg transition-all ${
                          orderType === type 
                            ? type === 'AI Execution' 
                                ? 'bg-gradient-to-r from-theme_blue to-purple-600 text-white shadow-md' 
                                : 'bg-card border border-border shadow-sm'
                            : 'text-muted-foreground hover:text-foreground'
                        }`}
                      >
                        {type}
                      </button>
                    ))}
                  </div>

                  {/* Quantity Input */}
                  <div className="space-y-2">
                    <label className="text-xs font-bold text-muted-foreground uppercase tracking-wider">Shares to Buy</label>
                    <div className="relative">
                      <input 
                        type="number" 
                        value={quantity}
                        onChange={(e) => setQuantity(e.target.value)}
                        className="w-full bg-background border-2 border-border focus:border-theme_blue focus:ring-4 focus:ring-theme_blue/10 rounded-2xl py-4 px-5 text-2xl font-bold transition-all outline-none"
                      />
                      <div className="absolute right-5 top-1/2 -translate-y-1/2 text-muted-foreground font-medium">
                        ≈ ${(totalValue).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </div>
                    </div>
                  </div>

                  {orderType === 'AI Execution' && (
                    <div className="p-4 bg-theme_blue/5 border border-theme_blue/20 rounded-2xl space-y-3">
                      <div className="flex items-center gap-2 text-sm font-bold text-theme_blue">
                        <Lock className="w-4 h-4" /> AI Guardrails Active
                      </div>
                      <div className="space-y-2 text-xs text-muted-foreground">
                        <div className="flex justify-between"><span>Smart Entry:</span> <span className="font-medium text-foreground">Waiting for 5m MACD crossover</span></div>
                        <div className="flex justify-between"><span>Stop Loss:</span> <span className="font-medium text-foreground">Trailing -1.5% (ATR)</span></div>
                        <div className="flex justify-between"><span>Take Profit:</span> <span className="font-medium text-foreground">Laddered near $191.00</span></div>
                      </div>
                    </div>
                  )}

                  {/* Submit Button */}
                  <button 
                    onClick={handleExecute}
                    className="w-full bg-theme_blue text-white py-4 rounded-2xl font-bold text-lg hover:bg-theme_blue/90 transition-all active:scale-[0.98] shadow-lg shadow-theme_blue/20 flex items-center justify-center gap-2"
                  >
                    Confirm {orderType} Order <ChevronRight className="w-5 h-5" />
                  </button>
                  <p className="text-center text-xs text-muted-foreground pt-2 flex items-center justify-center gap-1">
                    <AlertCircle className="w-3 h-3" /> Commission-free execution
                  </p>
                </motion.div>
              )}

              {step === 'Executing' && (
                <motion.div initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} className="flex flex-col items-center justify-center py-12 space-y-6">
                  <div className="relative w-20 h-20">
                    <div className="absolute inset-0 border-4 border-border rounded-full"></div>
                    <div className="absolute inset-0 border-4 border-theme_blue border-t-transparent rounded-full animate-spin"></div>
                    <div className="absolute inset-0 flex items-center justify-center">
                      <TrendingUp className="w-8 h-8 text-theme_blue" />
                    </div>
                  </div>
                  <div className="text-center">
                    <h3 className="font-display font-bold text-xl mb-1">Routing Order...</h3>
                    <p className="text-sm text-muted-foreground">Optimizing execution path via Smart Order Router</p>
                  </div>
                </motion.div>
              )}

              {step === 'Success' && (
                <motion.div initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} className="flex flex-col items-center justify-center py-12 space-y-6">
                  <div className="w-20 h-20 bg-theme_green/10 text-theme_green rounded-full flex items-center justify-center">
                    <CheckCircle2 className="w-10 h-10" />
                  </div>
                  <div className="text-center">
                    <h3 className="font-display font-bold text-xl mb-1">Order Sent!</h3>
                    <p className="text-sm text-muted-foreground">The AI engine is now managing your position.</p>
                  </div>
                </motion.div>
              )}

            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
};
