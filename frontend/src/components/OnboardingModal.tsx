import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Bot, LineChart, ShieldCheck, ArrowRight, Check } from 'lucide-react';

interface Props {
  isOpen: boolean;
  onClose: () => void;
}

export const OnboardingModal: React.FC<Props> = ({ isOpen, onClose }) => {
  const [step, setStep] = useState(0);

  const slides = [
    {
      title: "Welcome to AI Stock.",
      subtitle: "The world's most advanced autonomous trading platform, designed for everyone.",
      icon: <Bot className="w-12 h-12 text-theme_blue" />,
      imageBg: "bg-theme_blue/10"
    },
    {
      title: "Complexity, made invisible.",
      subtitle: "Switch seamlessly between Beginner and Pro modes. We hide the jargon until you're ready for it.",
      icon: <LineChart className="w-12 h-12 text-theme_green" />,
      imageBg: "bg-theme_green/10"
    },
    {
      title: "Trade with confidence.",
      subtitle: "Our XGBoost prediction engine and Smart Money Concepts protect your downside automatically.",
      icon: <ShieldCheck className="w-12 h-12 text-theme_yellow" />,
      imageBg: "bg-theme_yellow/10"
    }
  ];

  const handleNext = () => {
    if (step < slides.length - 1) {
      setStep(step + 1);
    } else {
      onClose();
    }
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <div className="fixed inset-0 z-[300] flex items-center justify-center p-4">
          <motion.div 
            initial={{ opacity: 0 }} 
            animate={{ opacity: 1 }} 
            exit={{ opacity: 0 }} 
            className="absolute inset-0 bg-background/90 backdrop-blur-xl"
          />

          <motion.div
            initial={{ opacity: 0, y: 40, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -20, scale: 0.95 }}
            transition={{ type: "spring", damping: 25, stiffness: 200 }}
            className="relative w-full max-w-lg bg-card border border-border shadow-2xl rounded-[2rem] overflow-hidden flex flex-col p-8 sm:p-12 text-center"
          >
            <AnimatePresence mode="wait">
              <motion.div 
                key={step}
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }}
                transition={{ duration: 0.2 }}
                className="flex flex-col items-center"
              >
                <div className={`w-24 h-24 rounded-3xl ${slides[step].imageBg} flex items-center justify-center mb-8 shadow-inner`}>
                  {slides[step].icon}
                </div>
                <h2 className="font-display font-bold text-3xl sm:text-4xl mb-4 tracking-tight">
                  {slides[step].title}
                </h2>
                <p className="text-muted-foreground text-lg sm:text-xl leading-relaxed mb-12">
                  {slides[step].subtitle}
                </p>
              </motion.div>
            </AnimatePresence>

            <div className="flex items-center justify-between mt-auto">
              <div className="flex gap-2">
                {slides.map((_, i) => (
                  <div 
                    key={i} 
                    className={`h-2 rounded-full transition-all duration-300 ${i === step ? 'w-8 bg-foreground' : 'w-2 bg-border'}`}
                  />
                ))}
              </div>
              
              <button 
                onClick={handleNext}
                className="bg-foreground text-background px-6 py-3 rounded-2xl font-bold text-sm sm:text-base hover:bg-foreground/90 transition-all active:scale-[0.98] flex items-center gap-2"
              >
                {step === slides.length - 1 ? (
                  <>Get Started <Check className="w-5 h-5" /></>
                ) : (
                  <>Continue <ArrowRight className="w-5 h-5" /></>
                )}
              </button>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
};
