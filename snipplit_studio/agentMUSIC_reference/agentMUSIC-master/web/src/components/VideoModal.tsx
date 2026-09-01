import { useEffect, useRef } from 'react';
import type { Video } from '../types';

interface Props {
  video: Video | null;
  onClose: () => void;
}

export function VideoModal({ video, onClose }: Props) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!video) return;
    const prevOverflow = document.body.style.overflow;
    const prevFocus = document.activeElement as HTMLElement | null;
    document.body.style.overflow = 'hidden';
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.body.style.overflow = prevOverflow;
      document.removeEventListener('keydown', onKey);
      prevFocus?.focus?.();
    };
  }, [video, onClose]);

  if (!video) return null;
  const src = video.download_url || video.url;

  return (
    <div
      className="modal-bg"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Просмотр видео"
    >
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <button
          ref={closeRef}
          className="modal-close"
          onClick={onClose}
          aria-label="Закрыть"
          type="button"
        >
          &#10005;
        </button>
        <video src={src} controls autoPlay poster={video.thumbnail_url} />
        <div className="modal-body">
          <div className="modal-title">{video.title || video.filename || video.id}</div>
          {video.description && <div className="modal-desc">{video.description}</div>}
          {video.hashtags && video.hashtags.length > 0 && (
            <div className="modal-tags">
              {video.hashtags.map((t) => (
                <span key={t} className="modal-tag">
                  #{t.replace(/^#/, '')}
                </span>
              ))}
            </div>
          )}
          {src && (
            <a className="modal-dl" href={src} download>
              Скачать
            </a>
          )}
        </div>
      </div>
    </div>
  );
}
