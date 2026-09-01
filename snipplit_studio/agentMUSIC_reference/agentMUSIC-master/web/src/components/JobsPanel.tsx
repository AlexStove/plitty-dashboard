import { useStopJob } from '../api/queries';
import type { Job } from '../types';

interface Props {
  jobs: Job[];
  notify: (msg: string, type?: 'ok' | 'err') => void;
}

export function JobsPanel({ jobs, notify }: Props) {
  const stop = useStopJob();
  if (jobs.length === 0) return null;

  const activeCount = jobs.filter((j) => j.status === 'running').length;

  const handleStop = async (jobId: string) => {
    if (!confirm('Остановить задачу?')) return;
    try {
      await stop.mutateAsync(jobId);
      notify('Задача остановлена');
    } catch {
      notify('Не удалось остановить', 'err');
    }
  };

  return (
    <div className="panel" style={{ marginBottom: 16 }}>
      <div className="panel-head">
        <div className="panel-title">Задачи</div>
        {activeCount > 0 && (
          <span
            className="panel-badge"
            style={{ color: 'var(--cyan)', background: 'rgba(0,210,255,.06)' }}
          >
            {activeCount} активных
          </span>
        )}
      </div>
      {jobs.slice(0, 6).map((j) => {
        const total = j.total ?? 0;
        const progress = j.progress ?? 0;
        const pct =
          total > 0 ? Math.round((progress / total) * 100) : j.status === 'done' ? 100 : 0;
        return (
          <div key={j.job_id} className="job">
            <div className="job-top">
              <span className="job-name">{j.track_name || j.job_id?.slice(0, 8)}</span>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <span
                  className={`badge ${
                    j.status === 'running'
                      ? 'badge-run'
                      : j.status === 'done'
                        ? 'badge-done'
                        : 'badge-fail'
                  }`}
                >
                  {j.status}
                </span>
                {j.status === 'running' && (
                  <button
                    type="button"
                    className="btn btn-sm"
                    style={{
                      padding: '3px 9px',
                      borderColor: 'rgba(239,68,68,.3)',
                      color: '#ef4444',
                      background: 'rgba(239,68,68,.05)',
                    }}
                    onClick={() => handleStop(j.job_id)}
                    aria-label="Остановить задачу"
                  >
                    &#9632;
                  </button>
                )}
              </div>
            </div>
            {j.current_message && <div className="job-msg">{j.current_message}</div>}
            <div
              className="pbar"
              role="progressbar"
              aria-valuenow={pct}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <div className="pfill" style={{ width: pct + '%' }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}
