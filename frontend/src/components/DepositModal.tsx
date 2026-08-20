import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Building2, CreditCard, ArrowRight, ShieldCheck, CheckCircle2 } from 'lucide-react';

interface Props {
  isOpen: boolean;
  onClose: () => void;
}

export const DepositModal: React.FC<Props> = ({ isOpen, onClose }) => {
  const [amount, setAmount] = useState('5000');
  const [method, setMethod] = useState<'bank' | 'card'>('bank');
  const [step, setStep] = useState<'input' | 'processing' | 'success'>('input');

  const handleDeposit = () => {
    setStep('processing');
    setTimeout(() => {
      setStep('success');
      setTimeout(() => {
        onClose();
        setTimeout(() => setStep('input'), 500);
      }, 2000);
    }, 1500);
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <div className="fixed inset-0 z-[200] flex items-end sm:items-center justify-center p-4 sm:p-0">
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
            <div className="px-6 py-4 flex items-center justify-between border-b border-border bg-background/50">
              <h3 className="font-display font-bold text-xl">Deposit Funds</h3>
              <button onClick={onClose} className="p-2 rounded-full hover:bg-border/50 text-muted-foreground transition-colors">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6">
              {step === 'input' && (
                <motion.div initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} className="space-y-6">
                  
                  {/* Amount Input */}
                  <div className="space-y-2">
                    <label className="text-xs font-bold text-muted-foreground uppercase tracking-wider">Amount (USD)</label>
                    <div className="relative">
                      <span className="absolute left-5 top-1/2 -translate-y-1/2 text-2xl font-bold text-muted-foreground">$</span>
                      <input 
                        type="number" 
                        value={amount}
                        onChange={(e) => setAmount(e.target.value)}
                        className="w-full bg-background border-2 border-border focus:border-theme_blue focus:ring-4 focus:ring-theme_blue/10 rounded-2xl py-4 pl-12 pr-5 text-3xl font-bold transition-all outline-none"
                      />
                    </div>
                  </div>

                  {/* Payment Method */}
                  <div className="space-y-3">
                    <label className="text-xs font-bold text-muted-foreground uppercase tracking-wider">Payment Method</label>
                    <div className="grid grid-cols-2 gap-3">
                      <button 
                        onClick={() => setMethod('bank')}
                        className={`p-4 rounded-2xl border-2 flex flex-col items-center justify-center gap-2 transition-all ${
                          method === 'bank' ? 'border-theme_blue bg-theme_blue/5 text-theme_blue' : 'border-border bg-background text-muted-foreground hover:border-border/80'
                        }`}
                      >
                        <Building2 className="w-6 h-6" />
                        <span className="font-bold text-sm">Bank Transfer</span>
                      </button>
                      <button 
                        onClick={() => setMethod('card')}
                        className={`p-4 rounded-2xl border-2 flex flex-col items-center justify-center gap-2 transition-all ${
                          method === 'card' ? 'border-theme_blue bg-theme_blue/5 text-theme_blue' : 'border-border bg-background text-muted-foreground hover:border-border/80'
                        }`}
                      >
                        <CreditCard className="w-6 h-6" />
                        <span className="font-bold text-sm">Debit Card</span>
                      </button>
                    </div>
                  </div>

                  {method === 'bank' && (
                    <div className="p-3 bg-background border border-border rounded-xl flex items-center justify-between text-sm">
                      <div className="flex items-center gap-2">
                        <div className="w-8 h-8 rounded-full bg-blue-500/20 text-blue-500 flex items-center justify-center"><Building2 className="w-4 h-4" /></div>
                        <div>
                          <p className="font-bold">Chase Checking</p>
                          <p className="text-xs text-muted-foreground">•••• 4321</p>
                        </div>
                      </div>
                      <span className="text-xs text-muted-foreground">Limit: $50k</span>
                    </div>
                  )}

                  <button 
                    onClick={handleDeposit}
                    className="w-full bg-foreground text-background py-4 rounded-2xl font-bold text-lg hover:bg-foreground/90 transition-all active:scale-[0.98] flex items-center justify-center gap-2 mt-4"
                  >
                    Deposit ${(parseFloat(amount) || 0).toLocaleString()} <ArrowRight className="w-5 h-5" />
                  </button>

                  <p className="text-center text-xs text-muted-foreground pt-2 flex items-center justify-center gap-1">
                    <ShieldCheck className="w-3 h-3" /> 256-bit bank-level encryption
                  </p>
                </motion.div>
              )}

              {step === 'processing' && (
                <motion.div initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} className="flex flex-col items-center justify-center py-12 space-y-6">
                  <div className="relative w-20 h-20">
                    <div className="absolute inset-0 border-4 border-border rounded-full"></div>
                    <div className="absolute inset-0 border-4 border-foreground border-t-transparent rounded-full animate-spin"></div>
                    <div className="absolute inset-0 flex items-center justify-center">
                      <ShieldCheck className="w-8 h-8 text-foreground" />
                    </div>
                  </div>
                  <div className="text-center">
                    <h3 className="font-display font-bold text-xl mb-1">Processing Payment</h3>
                    <p className="text-sm text-muted-foreground">Securely transferring funds...</p>
                  </div>
                </motion.div>
              )}

              {step === 'success' && (
                <motion.div initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} className="flex flex-col items-center justify-center py-12 space-y-6">
                  <div className="w-20 h-20 bg-theme_green/10 text-theme_green rounded-full flex items-center justify-center">
                    <CheckCircle2 className="w-10 h-10" />
                  </div>
                  <div className="text-center">
                    <h3 className="font-display font-bold text-xl mb-1">Deposit Successful</h3>
                    <p className="text-sm text-muted-foreground">${(parseFloat(amount) || 0).toLocaleString()} has been added to your buying power.</p>
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
