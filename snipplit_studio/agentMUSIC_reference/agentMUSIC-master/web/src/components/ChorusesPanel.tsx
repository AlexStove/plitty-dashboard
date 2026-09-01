import { useState } from 'react';
import type { Chorus } from '../types';

interface Props {
  choruses: Chorus[];
  selected: string;
  onSelect: (id: string) => void;
}

export function ChorusesPanel({ choruses, selected, onSelect }: Props) {
  const [playing, setPlaying] = useState<string | null>(null);
  const playingChorus = playing ? choruses.find((c) => c.id === playing) : null;

  return (
    <div className="panel">
      <div className="panel-head">
        <div className="panel-title">Припевы</div>
        <span
          className="panel-badge"
          style={{ color: 'var(--purple)', background: 'rgba(190,50,255,.06)' }}
        >
          {choruses.length}
        </span>
      </div>
      {choruses.length === 0 ? (
        <div className="empty">
          <div className="empty-icon" aria-hidden="true">
            🎤
          </div>
          <div>Загрузите трек</div>
        </div>
      ) : (
        <div>
          {playing && (
            <div className="ch-player">
              <div className="ch-player-name">{playingChorus?.name || playing}</div>
              <audio
                src={`/api/choruses/${playing}/audio`}
                controls
                autoPlay
                style={{ width: '100%', height: 28, borderRadius: 6 }}
                onEnded={() => setPlaying(null)}
              />
            </div>
          )}
          <div className="ch-list" role="listbox" aria-label="Припевы">
            {choruses.map((ch) => (
              <div
                key={ch.id}
                className={`ch ${selected === ch.id ? 'sel' : ''}`}
                role="option"
                aria-selected={selected === ch.id}
                tabIndex={0}
                onClick={() => onSelect(ch.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onSelect(ch.id);
                  }
                }}
              >
                <button
                  type="button"
                  className={`ch-play ${playing === ch.id ? 'on' : ''}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    setPlaying(playing === ch.id ? null : ch.id);
                  }}
                  aria-label={playing === ch.id ? 'Остановить' : 'Прослушать'}
                  style={{ border: 'none' }}
                >
                  {playing === ch.id ? '⏸' : '▶'}
                </button>
                <span className="ch-name">{ch.name || ch.id}</span>
                {ch.is_preview && (
                  <span
                    className="ch-id"
                    title="Извлечено из 30-сек превью — загрузите полный трек через MinIO"
                    style={{ color: '#f59e0b' }}
                  >
                    превью
                  </span>
                )}
                <span className="ch-id">{ch.id?.slice(0, 8)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
