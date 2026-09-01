import { useEffect } from 'react';
import type { ToastMsg } from '../types';

interface Props {
  toast: ToastMsg;
  onDone: () => void;
}

export function Toast({ toast, onDone }: Props) {
  useEffect(() => {
    const t = setTimeout(onDone, 3000);
    return () => clearTimeout(t);
  }, [onDone, toast]);

  return (
    <div
      className={`toast ${toast.type === 'ok' ? 'toast-ok' : 'toast-err'}`}
      role="status"
      aria-live="polite"
    >
      {toast.msg}
    </div>
  );
}
