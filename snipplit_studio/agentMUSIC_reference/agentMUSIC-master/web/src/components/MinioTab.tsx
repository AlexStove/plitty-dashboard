import { useState } from 'react';
import { useMinioImport, useMinioTracks } from '../api/queries';

interface Props {
  notify: (msg: string, type?: 'ok' | 'err') => void;
}

export function MinioTab({ notify }: Props) {
  const { data: tracks = [], refetch, isFetching } = useMinioTracks(true);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const mutation = useMinioImport();
  const tracksBucket = import.meta.env.VITE_MINIO_TRACKS_BUCKET || 'music-tracks';

  const toggle = (key: string) => {
    setSel((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const handleImport = async () => {
    if (sel.size === 0 || mutation.isPending) return;
    try {
      const r = await mutation.mutateAsync([...sel]);
      notify(`Импорт: ${r.success ?? 0}/${r.total ?? 0}`);
      setSel(new Set());
      await refetch();
    } catch {
      notify('Ошибка MinIO', 'err');
    }
  };

  return (
    <div>
      <div
        style={{
          marginBottom: 10,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <span style={{ fontSize: 12, color: 'var(--text2)' }}>MinIO: {tracksBucket}</span>
        <div style={{ display: 'flex', gap: 6 }}>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => refetch()}
            aria-label="Обновить список"
            disabled={isFetching}
          >
            &#8635;
          </button>
          {sel.size > 0 && (
            <button
              type="button"
              className="btn btn-sm btn-pink"
              onClick={handleImport}
              disabled={mutation.isPending}
            >
              {mutation.isPending ? '...' : `Импорт (${sel.size})`}
            </button>
          )}
        </div>
      </div>
      {tracks.length === 0 ? (
        <div className="empty">
          <div className="empty-icon" aria-hidden="true">
            📦
          </div>
          <div>Пусто</div>
        </div>
      ) : (
        <div className="minio-list">
          {tracks.map((t) => (
            <div
              key={t.key}
              className={`mi ${t.processed ? 'done' : ''}`}
              role="checkbox"
              aria-checked={sel.has(t.key)}
              tabIndex={t.processed ? -1 : 0}
              onClick={() => !t.processed && toggle(t.key)}
              onKeyDown={(e) => {
                if (!t.processed && (e.key === 'Enter' || e.key === ' ')) {
                  e.preventDefault();
                  toggle(t.key);
                }
              }}
            >
              <span aria-hidden="true">{sel.has(t.key) ? '☑' : '☐'}</span>
              <span className="mi-name">{t.title}</span>
              <span className="mi-art">{t.artist}</span>
              {t.processed && <span style={{ color: 'var(--green)' }}>✓</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
