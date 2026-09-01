import { useState } from 'react';
import { useGenerate } from '../api/queries';
import type { BgType, Orientation, Scenario } from '../types';

interface Props {
  notify: (msg: string, type?: 'ok' | 'err') => void;
  selectedChorus: string;
}

export function GeneratePanel({ notify, selectedChorus }: Props) {
  const [scenario, setScenario] = useState<Scenario>('karaoke');
  const [bgType, setBgType] = useState<BgType>('animated');
  const [orientation, setOrientation] = useState<Orientation>('portrait');
  const [videoCount, setVideoCount] = useState(1);
  const mutation = useGenerate();

  const disabled = !selectedChorus || mutation.isPending;

  const submit = async () => {
    if (disabled) return;
    try {
      await mutation.mutateAsync({
        chorus_id: selectedChorus,
        scenario,
        bg_type: bgType,
        orientation,
        videos_per_account: videoCount,
      });
      notify('Генерация запущена!');
    } catch {
      notify('Ошибка генерации', 'err');
    }
  };

  return (
    <div className="panel">
      <div className="panel-head">
        <div className="panel-title">Генерация</div>
      </div>
      <div className="form">
        <div className="form-row">
          <div className="form-group">
            <label className="form-label" htmlFor="gen-scenario">
              Сценарий
            </label>
            <select
              id="gen-scenario"
              className="form-select"
              value={scenario}
              onChange={(e) => setScenario(e.target.value as Scenario)}
            >
              <option value="karaoke">🎤 Караоке</option>
              <option value="slideshow">🎞 Слайдшоу</option>
              <option value="track_promo">📀 Track Promo</option>
              <option value="cover_alive">🖼 Cover Alive</option>
              <option value="pov_spotify">📱 POV Spotify</option>
            </select>
          </div>
          {scenario === 'karaoke' && (
            <div className="form-group">
              <label className="form-label" htmlFor="gen-bg">
                Фон
              </label>
              <select
                id="gen-bg"
                className="form-select"
                value={bgType}
                onChange={(e) => setBgType(e.target.value as BgType)}
              >
                <option value="animated">Анимированный</option>
                <option value="footage">Футаж</option>
              </select>
            </div>
          )}
        </div>
        <div className="form-row">
          <div className="form-group">
            <label className="form-label" htmlFor="gen-orientation">
              Ориентация
            </label>
            <select
              id="gen-orientation"
              className="form-select"
              value={orientation}
              onChange={(e) => setOrientation(e.target.value as Orientation)}
            >
              <option value="portrait">Портрет</option>
              <option value="landscape">Альбом</option>
            </select>
          </div>
          <div className="form-group">
            <label className="form-label" htmlFor="gen-count">
              Кол-во
            </label>
            <select
              id="gen-count"
              className="form-select"
              value={videoCount}
              onChange={(e) => setVideoCount(+e.target.value)}
            >
              {[1, 2, 3, 5].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </div>
        </div>
        <button
          type="button"
          className="btn btn-primary"
          onClick={submit}
          disabled={disabled}
          style={{ padding: '11px 20px', fontSize: 13 }}
        >
          {mutation.isPending ? 'Генерация...' : 'Сгенерировать'}
        </button>
      </div>
    </div>
  );
}
