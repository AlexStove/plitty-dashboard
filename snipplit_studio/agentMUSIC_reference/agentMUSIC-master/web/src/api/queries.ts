import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, jsonPost } from './client';
import type { Chorus, DownloadSource, GenerateParams, Job, MinioTrack, Stats, Video } from '../types';

const extract = <T>(v: unknown, key: string): T[] => {
  if (Array.isArray(v)) return v as T[];
  if (v && typeof v === 'object' && Array.isArray((v as Record<string, unknown>)[key])) {
    return (v as Record<string, unknown>)[key] as T[];
  }
  return [];
};

export const useStats = (enabled = true) =>
  useQuery<Stats>({
    queryKey: ['stats'],
    queryFn: () => api<Stats>('/api/stats'),
    refetchInterval: enabled ? 8000 : false,
    refetchIntervalInBackground: false,
    placeholderData: { tracks: 0, choruses: 0, videos: 0, active_jobs: 0 },
  });

export const useJobs = (enabled = true) =>
  useQuery<Job[]>({
    queryKey: ['jobs'],
    queryFn: async () => extract<Job>(await api('/api/jobs'), 'jobs'),
    refetchInterval: enabled ? 8000 : false,
    refetchIntervalInBackground: false,
    placeholderData: [],
  });

export const useChoruses = () =>
  useQuery<Chorus[]>({
    queryKey: ['choruses'],
    queryFn: async () => extract<Chorus>(await api('/api/choruses'), 'choruses'),
    refetchInterval: 15_000,
    refetchIntervalInBackground: false,
    placeholderData: [],
  });

export const useVideos = () =>
  useQuery<Video[]>({
    queryKey: ['videos'],
    queryFn: async () => extract<Video>(await api('/api/videos'), 'videos'),
    refetchInterval: 15_000,
    refetchIntervalInBackground: false,
    placeholderData: [],
  });

export const useMinioTracks = (enabled: boolean) =>
  useQuery<MinioTrack[]>({
    queryKey: ['minio'],
    queryFn: async () => {
      try {
        const v = await api<MinioTrack[] | { tracks?: MinioTrack[] }>('/api/tracks/minio');
        return Array.isArray(v) ? v : v.tracks ?? [];
      } catch {
        return [];
      }
    },
    enabled,
    placeholderData: [],
  });

export const useStopJob = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => jsonPost(`/api/jobs/${jobId}/stop`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
  });
};

export const useGenerate = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: GenerateParams) => jsonPost('/api/generate', params, 60_000),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] });
      qc.invalidateQueries({ queryKey: ['stats'] });
    },
  });
};

export const useSpotifyImport = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { url: string; source: DownloadSource }) =>
      jsonPost<{ count?: number }>(
        '/api/tracks/spotify',
        { url: vars.url, source: vars.source },
        120_000,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['stats'] });
      qc.invalidateQueries({ queryKey: ['choruses'] });
    },
  });
};

export const useMinioImport = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (keys: string[]) =>
      jsonPost<{ success?: number; total?: number }>(
        '/api/tracks/minio/import-batch',
        { keys },
        300_000,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['minio'] });
      qc.invalidateQueries({ queryKey: ['stats'] });
      qc.invalidateQueries({ queryKey: ['choruses'] });
    },
  });
};

export const refetchAll = (qc: ReturnType<typeof useQueryClient>) => {
  qc.invalidateQueries({ queryKey: ['stats'] });
  qc.invalidateQueries({ queryKey: ['jobs'] });
  qc.invalidateQueries({ queryKey: ['choruses'] });
  qc.invalidateQueries({ queryKey: ['videos'] });
};
