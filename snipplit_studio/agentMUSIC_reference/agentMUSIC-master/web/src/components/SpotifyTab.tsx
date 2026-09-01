import { useState } from 'react';
import { isValidSpotifyUrl } from '../api/client';
import { useSpotifyImport } from '../api/queries';
import type { DownloadSource } from '../types';

interface Props {
  notify: (msg: string, type?: 'ok' | 'err') => void;
}

export function SpotifyTab({ notify }: Props) {
  const [url, setUrl] = useState('');
  const [source, setSource] = useState<DownloadSource>('auto');
  const mutation = useSpotifyImport();
  const trimmed = url.trim();
  const invalid = trimmed !== '' && !isValidSpotifyUrl(trimmed);
  const disabled = mutation.isPending || !trimmed || invalid;

  const submit = async () => {
    if (disabled) return;
    try {
      const r = await mutation.mutateAsync({ url: trimmed, source });
      notify(`Загружено ${r.count ?? 0} треков`);
      setUrl('');
    } catch (e) {
      notify(`Ошибка Spotify: ${(e as Error).message}`, 'err');
    }
  };

  return (
    <div>
      <label
        htmlFor="spotify-url"
        style={{ marginBottom: 10, fontSize: 12, color: 'var(--text2)', display: 'block' }}
      >
        Ссылка на трек, артиста, альбом или плейлист Spotify
      </label>
      <div className="sp-row">
        <input
          id="spotify-url"
          className="sp-input"
          type="url"
          placeholder="https://open.spotify.com/..."
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') submit();
          }}
          aria-invalid={invalid}
        />
        <select
          className="sp-input"
          aria-label="Источник скачивания"
          value={source}
          onChange={(e) => setSource(e.target.value as DownloadSource)}
          disabled={mutation.isPending}
          style={{ flex: '0 0 auto', maxWidth: 140 }}
        >
          <option value="auto">Авто</option>
          <option value="deezer">Deezer</option>
          <option value="youtube">YouTube</option>
        </select>
        <button
          type="button"
          className="btn btn-green btn-sm"
          onClick={submit}
          disabled={disabled}
        >
          {mutation.isPending ? '...' : 'Загрузить'}
        </button>
      </div>
      {invalid && (
        <div style={{ marginTop: 6, fontSize: 10, color: '#ef4444' }}>
          Ожидается ссылка вида open.spotify.com/track/…
        </div>
      )}
    </div>
  );
}
