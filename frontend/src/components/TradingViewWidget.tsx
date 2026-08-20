import React, { useEffect, useRef, memo } from 'react';

interface Props {
  symbol?: string;
  isBeginnerMode?: boolean;
}

let _tvWidgetSeq = 0;

const TradingViewWidget: React.FC<Props> = ({ symbol = 'BSE:SENSEX', isBeginnerMode = false }) => {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let cancelled = false;
    const uid = `tv-widget-${++_tvWidgetSeq}`;
    container.innerHTML = '';

    const widgetDiv = document.createElement('div');
    widgetDiv.className = 'tradingview-widget-container__widget';
    widgetDiv.id = uid;
    widgetDiv.style.cssText = 'height:100%;width:100%;';
    container.appendChild(widgetDiv);

    const config = {
      autosize: true,
      symbol,
      interval: 'D',
      timezone: 'Asia/Kolkata',
      theme: 'dark',
      style: '1',
      locale: 'en',
      enable_publishing: false,
      backgroundColor: '#09090B',
      gridColor: 'rgba(255,255,255,0.06)',
      hide_top_toolbar: isBeginnerMode,
      hide_legend: isBeginnerMode,
      save_image: false,
      calendar: false,
      hide_volume: isBeginnerMode,
      support_host: 'https://www.tradingview.com',
      studies: isBeginnerMode ? [] : [
        'Volume@tv-basicstudies',
        'MACD@tv-basicstudies',
        'RSI@tv-basicstudies',
      ],
    };

    // Defer script insertion — if cleanup fires synchronously (React StrictMode
    // double-invocation), the timer is cancelled and the script never touches the
    // DOM, preventing TradingView's _replaceScript from getting a null querySelector.
    const timer = setTimeout(() => {
      if (cancelled || !containerRef.current) return;
      const script = document.createElement('script');
      script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
      script.type = 'text/javascript';
      script.async = true;
      script.textContent = JSON.stringify(config);
      container.appendChild(script);
    }, 0);

    return () => {
      cancelled = true;
      clearTimeout(timer);
      if (containerRef.current) containerRef.current.innerHTML = '';
    };
  }, [symbol, isBeginnerMode]);

  return (
    <div
      className="tradingview-widget-container"
      ref={containerRef}
      style={{ height: '100%', width: '100%', minHeight: '100%', borderRadius: '16px', overflow: 'hidden' }}
    />
  );
};

export default memo(TradingViewWidget);
