import { useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api, jsonPost } from '../api/client';
import { refetchAll } from '../api/queries';

interface Props {
  notify: (msg: string, type?: 'ok' | 'err') => void;
}

interface UplStatus {
  name: string;
  pct: number;
  msg: string;
}

export function UploadTab({ notify }: Props) {
  const [dragOver, setDragOver] = useState(false);
  const [uplStatus, setUplStatus] = useState<UplStatus | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const qc = useQueryClient();

  const uploadOne = async (file: File) => {
    setUplStatus({ name: file.name, pct: 10, msg: 'Загрузка...' });
    const fd = new FormData();
    fd.append('file', file);
    setUplStatus((s) => s && { ...s, pct: 40, msg: 'Отправка...' });
    const r = await fetch('/api/tracks/upload', { method: 'POST', body: fd });
    if (!r.ok) throw new Error('upload failed');
    const track = (await r.json()) as { id: string };
    setUplStatus((s) => s && { ...s, pct: 70, msg: 'Обработка...' });
    try {
      await jsonPost(`/api/tracks/${track.id}/process`, {}, 600_000);
      setUplStatus({ name: file.name, pct: 100, msg: 'Готово!' });
    } catch {
      setUplStatus({ name: file.name, pct: 100, msg: 'Загружен' });
    }
  };

  const handleFiles = async (list: FileList | File[] | null | undefined) => {
    const files = Array.from(list || []).filter((f) => f && f.type.startsWith('audio/'));
    if (files.length === 0) return;
    if (files.length === 1) {
      try {
        await uploadOne(files[0]);
        notify(`"${files[0].name}" обработан`);
      } catch {
        setUplStatus({ name: files[0].name, pct: 0, msg: 'Ошибка' });
        notify('Ошибка загрузки', 'err');
      }
      refetchAll(qc);
      return;
    }
    let ok = 0;
    let fail = 0;
    for (let i = 0; i < files.length; i++) {
      setUplStatus({
        name: `${files[i].name} (${i + 1}/${files.length})`,
        pct: Math.round((i / files.length) * 100),
        msg: 'Обработка...',
      });
      try {
        await uploadOne(files[i]);
        ok++;
      } catch {
        fail++;
      }
    }
    notify(
      `Обработано ${ok}/${files.length}${fail ? `, ошибок: ${fail}` : ''}`,
      fail ? 'err' : 'ok',
    );
    refetchAll(qc);
  };

  return (
    <div>
      <div
        className={`drop ${dragOver ? 'over' : ''}`}
        role="button"
        tabIndex={0}
        aria-label="Загрузить аудиофайлы"
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          handleFiles(e.dataTransfer.files);
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onClick={() => fileRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            fileRef.current?.click();
          }
        }}
      >
        <input
          ref={fileRef}
          type="file"
          accept="audio/*"
          multiple
          onChange={(e) => {
            if (e.target.files?.length) handleFiles(e.target.files);
          }}
        />
        <div className="drop-icon" aria-hidden="true">
          🎵
        </div>
        <div className="drop-text">Перетащите аудио сюда</div>
        <div className="drop-hint">MP3, WAV, FLAC, M4A, OGG — можно несколько</div>
      </div>
      {uplStatus && (
        <div className="upl">
          <div className="upl-name">{uplStatus.name}</div>
          <div
            className="upl-bar"
            role="progressbar"
            aria-valuenow={uplStatus.pct}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div className="upl-fill" style={{ width: uplStatus.pct + '%' }} />
          </div>
          <div className="upl-msg">{uplStatus.msg}</div>
        </div>
      )}
    </div>
  );
}
