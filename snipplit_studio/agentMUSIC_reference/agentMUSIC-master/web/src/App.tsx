import { useEffect, useState } from 'react';
import { Header } from './components/Header';
import { VinylDisc } from './components/VinylDisc';
import { SourceTabs } from './components/SourceTabs';
import { GeneratePanel } from './components/GeneratePanel';
import { ChorusesPanel } from './components/ChorusesPanel';
import { JobsPanel } from './components/JobsPanel';
import { VideosGrid } from './components/VideosGrid';
import { VideoModal } from './components/VideoModal';
import { Toast } from './components/Toast';
import { useChoruses, useJobs, useStats, useVideos } from './api/queries';
import { useLiveEvents } from './hooks/useSSE';
import { useToast } from './hooks/useToast';
import type { Video } from './types';

export default function App() {
  const statsQ = useStats();
  const jobsQ = useJobs();
  const chorusesQ = useChoruses();
  const videosQ = useVideos();
  useLiveEvents(true);

  const [selChorus, setSelChorus] = useState<string>('');
  const [modalVideo, setModalVideo] = useState<Video | null>(null);
  const { toast, notify, clearToast } = useToast();

  const choruses = chorusesQ.data ?? [];
  const jobs = jobsQ.data ?? [];
  const stats = statsQ.data ?? { tracks: 0, choruses: 0, videos: 0, active_jobs: 0 };
  const videos = videosQ.data ?? [];

  useEffect(() => {
    if (!selChorus && choruses.length > 0 && choruses[0].id) {
      setSelChorus(choruses[0].id);
    }
  }, [choruses, selChorus]);

  const activeJobs = jobs.filter((j) => j.status === 'running');
  const isPlaying = activeJobs.length > 0;
  const loading = statsQ.isFetching && !statsQ.data;

  return (
    <>
      <Header loading={loading} />
      <VinylDisc isPlaying={isPlaying} stats={stats} activeJobs={activeJobs.length} />
      <main id="main-content" className="bottom-section">
        <SourceTabs notify={notify} />
        <div className="grid2">
          <GeneratePanel notify={notify} selectedChorus={selChorus} />
          <ChorusesPanel choruses={choruses} selected={selChorus} onSelect={setSelChorus} />
        </div>
        <JobsPanel jobs={jobs} notify={notify} />
        <VideosGrid videos={videos} onOpen={setModalVideo} />
      </main>
      <VideoModal video={modalVideo} onClose={() => setModalVideo(null)} />
      {toast && <Toast toast={toast} onDone={clearToast} />}
    </>
  );
}
