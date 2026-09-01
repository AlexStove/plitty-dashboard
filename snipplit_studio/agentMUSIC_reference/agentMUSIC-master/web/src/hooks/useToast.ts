import { useCallback, useState } from 'react';
import type { ToastMsg } from '../types';

export function useToast() {
  const [toast, setToast] = useState<ToastMsg | null>(null);
  const notify = useCallback((msg: string, type: ToastMsg['type'] = 'ok') => {
    setToast({ msg, type });
  }, []);
  return { toast, notify, clearToast: () => setToast(null) };
}
