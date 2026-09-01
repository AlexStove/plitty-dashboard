import { useMemo } from 'react';
import type { Video } from '../types';

interface Props {
  videos: Video[];
  onOpen: (video: Video) => void;
}

export function VideosGrid({ videos, onOpen }: Props) {
  const recent = useMemo(() => {
    const keyOf = (v: Video) => v.rendered_at || v.created_at || '';
    return [...videos]
      .sort((a, b) => keyOf(b).localeCompare(keyOf(a)))
      .slice(0, 12);
  }, [videos]);

  return (
    <div className="panel">
      <div className="panel-head">
        <div className="panel-title">Видео</div>
        <span
          className="panel-badge"
          style={{ color: 'var(--pink)', background: 'rgba(255,60,170,.06)' }}
        >
          {recent.length}
        </span>
      </div>
      {recent.length === 0 ? (
        <div className="empty">
          <div className="empty-icon" aria-hidden="true">
            🎬
          </div>
          <div>Нет видео</div>
        </div>
      ) : (
        <div className="vid-grid">
          {recent.map((v) => {
            const src = v.download_url || v.url;
            const ts = v.rendered_at || v.created_at;
            return (
              <div
                key={v.id || v.filename}
                className="vid-card"
                role="button"
                tabIndex={0}
                onClick={() => onOpen(v)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onOpen(v);
                  }
                }}
              >
                <div className="vid-thumb">
                  {v.thumbnail_url ? (
                    <img src={v.thumbnail_url} alt="" />
                  ) : src ? (
                    <video src={`${src}#t=0.5`} preload="auto" muted playsInline />
                  ) : null}
                  <div className="vid-over">
                    <div className="vid-play" aria-hidden="true">
                      ▶
                    </div>
                  </div>
                </div>
                <div className="vid-info">
                  <div className="vid-title">{v.title || v.filename || v.id}</div>
                  <div className="vid-meta">
                    {v.scenario && <span className="vid-badge">{v.scenario}</span>}
                    {ts && <span>{new Date(ts).toLocaleDateString('ru')}</span>}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
