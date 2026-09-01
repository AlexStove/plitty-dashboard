import { useEffect, useState } from 'react';
import { MinioTab } from './MinioTab';
import { SpotifyTab } from './SpotifyTab';
import { UploadTab } from './UploadTab';
import type { TabId } from '../types';

const VALID: TabId[] = ['upload', 'spotify', 'minio'];

const readTabFromUrl = (): TabId => {
  const t = new URLSearchParams(location.search).get('tab');
  return VALID.includes(t as TabId) ? (t as TabId) : 'upload';
};

interface Props {
  notify: (msg: string, type?: 'ok' | 'err') => void;
}

export function SourceTabs({ notify }: Props) {
  const [tab, setTab] = useState<TabId>(() => readTabFromUrl());

  useEffect(() => {
    const url = new URL(location.href);
    if (tab === 'upload') url.searchParams.delete('tab');
    else url.searchParams.set('tab', tab);
    history.replaceState(null, '', url.toString());
  }, [tab]);

  useEffect(() => {
    const onPop = () => setTab(readTabFromUrl());
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  return (
    <>
      <div className="tabs" role="tablist" aria-label="Источники треков">
        {(
          [
            { id: 'upload', l: 'Загрузить' },
            { id: 'spotify', l: 'Spotify' },
            { id: 'minio', l: 'MinIO' },
          ] as const
        ).map((t) => (
          <button
            key={t.id}
            type="button"
            className={`tab ${tab === t.id ? 'act' : ''}`}
            onClick={() => setTab(t.id)}
            role="tab"
            aria-selected={tab === t.id}
            tabIndex={tab === t.id ? 0 : -1}
          >
            {t.l}
          </button>
        ))}
      </div>
      <div className="panel">
        {tab === 'upload' && <UploadTab notify={notify} />}
        {tab === 'spotify' && <SpotifyTab notify={notify} />}
        {tab === 'minio' && <MinioTab notify={notify} />}
      </div>
    </>
  );
}
