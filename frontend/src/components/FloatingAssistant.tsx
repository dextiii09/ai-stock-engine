import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Bot, X, Send, Sparkles, TrendingUp, Minimize2, Maximize2, Trash2 } from 'lucide-react';

interface Message {
  id: string;
  role: 'ai' | 'user';
  text: string;
  timestamp: number;
}

export const FloatingAssistant = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [isMinimized, setIsMinimized] = useState(false);
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  
  // Load from local storage or set default
  const [messages, setMessages] = useState<Message[]>(() => {
    const saved = localStorage.getItem('ai_chat_history');
    if (saved) {
      try {
        return JSON.parse(saved);
      } catch (e) {
        console.error("Failed to parse chat history");
      }
    }
    return [{ 
      id: 'default-1', 
      role: 'ai', 
      text: 'Hello! I am your autonomous trading brain. Ask me about a specific stock, your portfolio risk, or market sentiment.',
      timestamp: Date.now()
    }];
  });

  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Sync to local storage on change
  useEffect(() => {
    localStorage.setItem('ai_chat_history', JSON.stringify(messages));
  }, [messages]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isOpen, isMinimized, isTyping]);

  const handleClearHistory = (e: React.MouseEvent) => {
    e.stopPropagation();
    setMessages([{ 
      id: Date.now().toString(), 
      role: 'ai', 
      text: 'Chat history cleared. How can I help you today?',
      timestamp: Date.now()
    }]);
  };

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!input.trim()) return;

    const userText = input.trim();
    setInput('');
    
    // Add user message
    setMessages(prev => [...prev, { 
      id: Date.now().toString(), 
      role: 'user', 
      text: userText,
      timestamp: Date.now()
    }]);
    
    setIsTyping(true);

    // Simulate AI thinking and responding
    setTimeout(() => {
      let reply = "I'm analyzing the market data for that request...";
      
      if (userText.toLowerCase().includes('aapl')) {
        reply = "Apple (AAPL) is currently showing a bullish CHoCH on the 1H timeframe. My XGBoost model predicts a 78% probability of hitting $192.50 by Friday. Would you like me to queue an automated limit order?";
      } else if (userText.toLowerCase().includes('portfolio') || userText.toLowerCase().includes('drop')) {
        reply = "Your portfolio dropped 1.2% today primarily due to weakness in the tech sector (QQQ -1.5%). However, your hedge positions in Energy (XLE) mitigated further losses. Your overall risk profile remains Low.";
      } else if (userText.toLowerCase().includes('hello') || userText.toLowerCase().includes('hi')) {
        reply = "Hello! I am monitoring 8,432 global equities in real-time. How can I assist your trading today?";
      }

      setMessages(prev => [...prev, { 
        id: (Date.now() + 1).toString(), 
        role: 'ai', 
        text: reply,
        timestamp: Date.now()
      }]);
      setIsTyping(false);
    }, 1500);
  };

  // Allow Enter to submit
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <>
      {/* Floating Button */}
      <AnimatePresence>
        {!isOpen && (
          <motion.button
            initial={{ scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0, opacity: 0 }}
            onClick={() => { setIsOpen(true); setIsMinimized(false); }}
            className="fixed bottom-6 right-6 z-[100] bg-theme_blue text-white p-4 rounded-full shadow-2xl shadow-theme_blue/30 hover:scale-105 active:scale-95 transition-all flex items-center justify-center group"
          >
            <Bot className="w-6 h-6 group-hover:rotate-12 transition-transform" />
            <span className="absolute -top-2 -right-2 bg-theme_red text-white text-[10px] font-bold px-1.5 py-0.5 rounded-full border-2 border-background">
              1
            </span>
          </motion.button>
        )}
      </AnimatePresence>

      {/* Chat Window */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: 20, scale: 0.95 }}
            animate={{ 
              opacity: 1, 
              y: 0, 
              scale: 1,
              height: isMinimized ? '60px' : '600px'
            }}
            exit={{ opacity: 0, y: 20, scale: 0.95 }}
            transition={{ type: 'spring', damping: 25, stiffness: 200 }}
            className="fixed bottom-6 right-6 z-[100] w-[400px] max-w-[calc(100vw-3rem)] bg-card border border-border shadow-2xl rounded-2xl overflow-hidden flex flex-col"
          >
            {/* Header */}
            <div 
              className="p-4 bg-background/80 backdrop-blur-md border-b border-border flex items-center justify-between cursor-pointer"
              onClick={() => setIsMinimized(!isMinimized)}
            >
              <div className="flex items-center gap-3">
                <div className="relative">
                  <div className="w-8 h-8 rounded-full bg-theme_blue/20 flex items-center justify-center">
                    <Bot className="w-4 h-4 text-theme_blue" />
                  </div>
                  <div className="absolute bottom-0 right-0 w-2.5 h-2.5 bg-theme_green rounded-full border-2 border-card"></div>
                </div>
                <div>
                  <h3 className="font-bold text-sm">Ask AI</h3>
                  <p className="text-[10px] text-muted-foreground flex items-center gap-1">
                    <Sparkles className="w-3 h-3 text-theme_blue" /> Powered by DeepMind
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-1">
                {!isMinimized && (
                  <button 
                    onClick={handleClearHistory}
                    className="p-1.5 rounded-md hover:bg-theme_red/10 hover:text-theme_red text-muted-foreground transition-colors mr-1"
                    title="Clear Chat History"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                )}
                <button 
                  onClick={(e) => { e.stopPropagation(); setIsMinimized(!isMinimized); }}
                  className="p-1.5 rounded-md hover:bg-border/50 text-muted-foreground transition-colors"
                >
                  {isMinimized ? <Maximize2 className="w-4 h-4" /> : <Minimize2 className="w-4 h-4" />}
                </button>
                <button 
                  onClick={(e) => { e.stopPropagation(); setIsOpen(false); }}
                  className="p-1.5 rounded-md hover:bg-border/50 text-muted-foreground transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* Chat Area (Hidden when minimized) */}
            {!isMinimized && (
              <>
                <div className="flex-1 overflow-y-auto p-4 space-y-4 bg-background/30">
                  {messages.map((msg) => (
                    <motion.div 
                      key={msg.id}
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      className={`flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}
                    >
                      <div className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-sm ${
                        msg.role === 'user' 
                          ? 'bg-theme_blue text-white rounded-br-sm' 
                          : 'bg-card border border-border text-foreground rounded-bl-sm'
                      }`}>
                        {msg.text}
                      </div>
                      <span className="text-[10px] text-muted-foreground mt-1 mx-1">
                        {new Date(msg.timestamp).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
                      </span>
                    </motion.div>
                  ))}
                  
                  {isTyping && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex justify-start">
                      <div className="bg-card border border-border rounded-2xl rounded-bl-sm px-4 py-3 flex gap-1 items-center h-[44px]">
                        <div className="w-2 h-2 bg-theme_blue rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></div>
                        <div className="w-2 h-2 bg-theme_blue rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></div>
                        <div className="w-2 h-2 bg-theme_blue rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></div>
                      </div>
                    </motion.div>
                  )}
                  <div ref={messagesEndRef} />
                </div>

                {/* Input Area */}
                <div className="p-3 bg-background border-t border-border">
                  <div className="flex gap-2 mb-3 overflow-x-auto pb-1 hide-scrollbar">
                    <button 
                      onClick={() => { setInput('Is AAPL a buy?'); }} 
                      className="shrink-0 text-xs font-medium px-3 py-1.5 bg-card border border-border rounded-full hover:bg-border/50 hover:text-theme_blue transition-colors whitespace-nowrap"
                    >
                      Is AAPL a buy?
                    </button>
                    <button 
                      onClick={() => { setInput('Why did my portfolio drop?'); }} 
                      className="shrink-0 text-xs font-medium px-3 py-1.5 bg-card border border-border rounded-full hover:bg-border/50 hover:text-theme_blue transition-colors whitespace-nowrap flex items-center gap-1"
                    >
                      <TrendingUp className="w-3 h-3" /> Analyze Portfolio
                    </button>
                  </div>
                  
                  <form onSubmit={handleSubmit} className="relative flex items-center">
                    <textarea
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyDown={handleKeyDown}
                      placeholder="Ask anything..."
                      className="w-full bg-card border border-border rounded-xl py-3 pl-4 pr-12 text-sm focus:outline-none focus:border-theme_blue/50 transition-colors resize-none h-[46px] overflow-hidden leading-relaxed"
                      rows={1}
                    />
                    <button 
                      type="submit"
                      disabled={!input.trim() || isTyping}
                      className="absolute right-2 p-2 bg-theme_blue text-white rounded-lg disabled:opacity-50 disabled:cursor-not-allowed hover:bg-theme_blue/90 transition-colors"
                    >
                      <Send className="w-4 h-4" />
                    </button>
                  </form>
                  <p className="text-[10px] text-center text-muted-foreground mt-2">
                    AI can make mistakes. Verify trades before executing.
                  </p>
                </div>
              </>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
};
