import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { LiveEvent } from '../types';

export function useLiveEvents(enabled: boolean = true) {
  const qc = useQueryClient();
  useEffect(() => {
    if (!enabled) return;
    let es: EventSource | null = null;
    let closed = false;
    let retryTimer: number | null = null;

    const connect = () => {
      if (closed) return;
      es = new EventSource('/api/events');
      es.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data) as LiveEvent;
          if (data.stats) qc.setQueryData(['stats'], data.stats);
          if (data.jobs) qc.setQueryData(['jobs'], data.jobs);
        } catch {
          /* ignore */
        }
      };
      es.onerror = () => {
        es?.close();
        es = null;
        if (closed) return;
        retryTimer = window.setTimeout(connect, 3000);
      };
    };

    connect();

    return () => {
      closed = true;
      es?.close();
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, [enabled, qc]);
}
