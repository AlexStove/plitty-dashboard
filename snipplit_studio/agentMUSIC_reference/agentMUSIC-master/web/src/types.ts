export interface Stats {
  tracks: number;
  choruses: number;
  videos: number;
  active_jobs?: number;
}

export interface Job {
  job_id: string;
  status: 'running' | 'done' | 'failed' | string;
  progress?: number;
  total?: number;
  track_name?: string;
  current_message?: string;
  [k: string]: unknown;
}

export interface Chorus {
  id: string;
  name?: string;
  is_preview?: boolean;
  [k: string]: unknown;
}

export interface Video {
  id?: string;
  filename?: string;
  title?: string;
  description?: string;
  hashtags?: string[];
  url?: string;
  download_url?: string;
  thumbnail_url?: string;
  scenario?: string;
  rendered_at?: string;
  created_at?: string;
  [k: string]: unknown;
}

export interface MinioTrack {
  key: string;
  title: string;
  artist: string;
  processed?: boolean;
}

export type TabId = 'upload' | 'spotify' | 'minio';
export type DownloadSource = 'auto' | 'deezer' | 'youtube';
export type Scenario = 'karaoke' | 'slideshow' | 'track_promo' | 'cover_alive' | 'pov_spotify';
export type BgType = 'animated' | 'footage';
export type Orientation = 'portrait' | 'landscape';

export interface ToastMsg {
  msg: string;
  type: 'ok' | 'err';
}

export interface GenerateParams {
  chorus_id: string;
  scenario: Scenario;
  bg_type: BgType;
  orientation: Orientation;
  videos_per_account: number;
}

export interface LiveEvent {
  stats?: Stats;
  jobs?: Job[];
}
