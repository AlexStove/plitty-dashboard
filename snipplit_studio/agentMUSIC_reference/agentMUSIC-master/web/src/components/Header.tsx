import { useQueryClient } from '@tanstack/react-query';
import { refetchAll } from '../api/queries';

interface Props {
  loading: boolean;
}

export function Header({ loading }: Props) {
  const qc = useQueryClient();
  return (
    <>
      <a href="#main-content" className="skip-link">
        Перейти к содержимому
      </a>
      <header className="hdr">
        <div className="hdr-brand">
          <div className="hdr-logo" aria-hidden="true">
            &#9835;
          </div>
          <div>
            <div className="hdr-title">agentMUSIC</div>
            <div className="hdr-sub">Music Video Engine</div>
          </div>
        </div>
        <button
          type="button"
          className="btn"
          onClick={() => refetchAll(qc)}
          aria-label="Обновить данные"
          disabled={loading}
        >
          {loading ? '...' : 'Обновить'}
        </button>
      </header>
    </>
  );
}
