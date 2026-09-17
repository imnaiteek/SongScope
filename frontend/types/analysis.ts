/* Mirrors shared/analysis-result.schema.json (engine schema_version 1). */

export type ConfidenceLevel = "high" | "medium" | "low";
export type Certainty = "detected" | "estimated" | "inferred" | "uncertain";

export interface Confident {
  available?: boolean;
  confidence: number;
  confidence_level: ConfidenceLevel;
  status: Certainty;
  message: string | null;
}

export interface Metadata {
  title: string | null;
  artist: string | null;
  album: string | null;
  year: string | null;
  duration: number;
  sample_rate: number | null;
  channels: number | null;
  bit_depth: number | null;
  bit_rate: number | null;
  format: string | null;
  codec: string | null;
  file_size: number;
  source_type: "upload" | "youtube";
  filename: string | null;
  youtube: {
    video_id: string;
    url: string;
    title?: string | null;
    channel?: string | null;
    thumbnail?: string | null;
    view_count?: number | null;
    upload_date?: string | null;
    license?: string | null;
  } | null;
}

export interface TempoAlt {
  bpm: number;
  relation: "half-time" | "double-time";
  salience: number;
  plausibility: number;
}

export interface Tempo extends Confident {
  bpm: number | null;
  bpm_rounded: number | null;
  category: string | null;
  alternatives: TempoAlt[];
  alternative_bpm: number | null;
  alternative_relation: string | null;
  octave_ambiguous: boolean;
  estimates: Record<string, number | null>;
  stability: number | null;
  drift_percent?: number | null;
  timing_jitter_ms?: number | null;
  sections: { start: number; end: number; bpm: number }[];
  has_tempo_changes: boolean;
  tempo_varies?: boolean;
  curve: { times: number[]; bpm: number[] };
  components?: Record<string, number>;
}

export interface Rhythm {
  available: boolean;
  beats: number[];
  beat_strengths: number[];
  beat_count: number;
  beat_interval_s: number | null;
  tempo_stability: number | null;
  onset_count?: number;
  onset_density: number;
  rhythm_density?: number;
  syncopation?: number;
  onset_positions?: Record<string, number>;
  onsets: number[];
  downbeats: number[];
  message?: string;
}

export interface Meter extends Confident {
  signature: string | null;
  tendency?: string | null;
  reliable: boolean;
  beats_per_bar: number | null;
  beat_unit?: string;
  subdivision: string | null;
  subdivision_confidence?: number;
  candidates: { beats_per_bar: number; signature: string; score: number }[];
  bars: number;
  components?: Record<string, unknown>;
}

export interface Key extends Confident {
  key: string | null;
  tonic: string | null;
  tonic_pc: number | null;
  mode: "major" | "minor" | null;
  alternative_key: string | null;
  alternative_relation: string | null;
  candidates: { key: string; score: number }[];
  scale_confidence: number;
  method_votes: Record<string, string>;
  tuning_cents: number;
  reference_a4_hz: number;
  most_prominent_pitch_class: string;
  chroma_distribution: Record<string, number>;
  components: Record<string, number>;
  changes: { start: number; end: number; key: string; confidence: number }[];
}

export interface ChordItem {
  start: number;
  end: number;
  chord: string;
  root: number | null;
  quality: string | null;
  confidence: number;
}

export interface Chords extends Confident {
  items: ChordItem[];
  unique_chords: number;
  changes_per_minute: number | null;
  mean_chord_duration_s: number;
  chord_coverage: number;
  most_common: { chord: string; seconds: number; share: number }[];
  vocabulary: string[];
  method: string;
}

export interface Progression {
  chords: string[];
  display: string;
  numerals: string[] | null;
  numerals_display: string | null;
  occurrences: { start: number; end: number }[];
  count: number;
  coverage: number;
  sections: number[];
  confidence: number;
}

export interface ProgressionBlock extends Confident {
  main: Progression | null;
  others: Progression[];
  by_section: { section_index: number; label: string; start: number; end: number; chords: string[]; progression: string | null }[];
}

export interface Harmony extends Confident {
  tonal_center: string | null;
  key: string | null;
  chroma_distribution: { pitch_class: string; value: number }[];
  chroma_entropy: number;
  harmonic_complexity: number;
  complexity_label: string;
  unique_chords: number;
  chord_changes_per_minute: number | null;
  non_diatonic_share: number;
  extended_chord_share: number;
  harmonic_stability: number;
  stability_label: string;
  chromagram: { seconds_per_frame: number; pitch_classes: string[]; values: number[][] };
}

export interface Section {
  start: number;
  end: number;
  label: string;
  display_label: string;
  group: string;
  confidence: number;
  relative_energy_db?: number;
  boundary_strength?: number;
}

export interface Structure extends Confident {
  sections: Section[];
  sequence: string;
  group_sequence?: string;
  ssm: { size: number; seconds_per_cell: number; values: number[][] } | null;
  novelty?: { times: number[]; values: number[] };
}

export interface DrumInstrument {
  present: boolean;
  pattern: string;
  slot_probabilities: number[];
  consistency: number;
}

export interface Drums extends Confident {
  estimated: boolean;
  source?: string;
  beats_per_bar?: number;
  slots_per_beat?: number;
  slot_labels?: string[];
  bars_analyzed: number;
  instruments: Record<string, DrumInstrument>;
}

export interface Pitch extends Confident {
  source: string;
  voiced_fraction: number;
  fundamental_hz_median?: number;
  average_note?: string;
  average_hz?: number;
  lowest_note: string | null;
  lowest_hz?: number;
  highest_note: string | null;
  highest_hz?: number;
  range_semitones?: number;
  range_description?: string;
  most_frequent_note?: string;
  most_frequent_pitch_class?: string;
  pitch_class_histogram?: Record<string, number>;
  contour: { times: number[]; hz: (number | null)[]; midi: (number | null)[] };
  events: { start: number; end: number; midi: number; note: string; hz: number }[];
}

export interface LoudSeries {
  times: number[];
  lufs: (number | null)[];
}

export interface Loudness extends Confident {
  integrated_lufs: number | null;
  true_peak_dbtp: number | null;
  sample_peak_dbfs: number | null;
  rms_dbfs: number | null;
  crest_factor_db: number | null;
  loudness_range_lu: number | null;
  plr_db: number | null;
  dynamic_range_db: number | null;
  max_momentary_lufs: number | null;
  max_short_term_lufs: number | null;
  clipping_events: number;
  stereo: { correlation: number; side_to_mid_ratio: number } | null;
  character: string;
  momentary: LoudSeries;
  short_term: LoudSeries;
  method: string;
}

export interface Stat {
  mean: number | null;
  std: number | null;
  p10: number | null;
  p90: number | null;
}

export interface Band {
  key: string;
  name: string;
  low_hz: number;
  high_hz: number;
  energy_share: number;
  level_db: number;
  tilt_corrected_db: number | null;
}

export interface Spectrum extends Confident {
  summary: {
    brightness: string;
    texture: string;
    emphasized_regions: string[];
    peak_frequency_hz: number;
    peak_frequency_note: string | null;
  };
  centroid_hz: Stat;
  bandwidth_hz: Stat;
  rolloff_hz: Stat;
  flatness: Stat;
  zero_crossing_rate: Stat;
  rms_db: Stat;
  contrast_db: Record<string, number>;
  bands: Band[];
  ltas: { freqs: number[]; db: number[] };
  series: Record<string, { times: number[]; values: number[] }>;
  spectrogram: { freqs: number[]; seconds_per_frame: number; db: number[][] };
}

export interface StemResult {
  integrated_lufs: number | null;
  rms_dbfs: number | null;
  energy_share: number;
  spectral_centroid_hz: number | null;
  brightness: string;
  bands: { name: string; energy_share: number }[];
  activity: LoudSeries;
  audio_file: string;
  pitch?: Partial<Pitch>;
  tempo?: { bpm: number | null; confidence: number; confidence_level: ConfidenceLevel; onset_density: number };
}

export interface StemsResults extends Confident {
  model: string;
  stems: Record<string, StemResult>;
  audio_available: boolean;
}

export interface AnalysisResults {
  schema_version: number;
  engine_version: string;
  metadata: Metadata;
  overview: {
    bpm: number | null;
    key: string | null;
    meter: string | null;
    duration: number;
    integrated_lufs: number | null;
    overall_confidence: number;
    overall_confidence_level: ConfidenceLevel;
  };
  summary: {
    text: string;
    sentences: string[];
    highlights: { label: string; value: string; confidence: number; confidence_level: ConfidenceLevel; status: Certainty }[];
    generated_from: string;
  };
  tempo: Tempo;
  rhythm: Rhythm;
  meter: Meter;
  key: Key;
  chords: Chords;
  progression: ProgressionBlock;
  harmony: Harmony;
  structure: Structure;
  drums: Drums;
  pitch: Pitch;
  loudness: Loudness;
  spectrum: Spectrum;
  waveform: { peaks_per_second: number; peaks: number[]; max_amplitude: number };
  errors: { stage: string; component: string; message: string }[];
  warnings: string[];
  timings: Record<string, number>;
}

export type JobStatus = "queued" | "processing" | "completed" | "failed" | "cancelled";

export interface StageState {
  key: string;
  label: string;
  state: "pending" | "active" | "done" | "failed";
}

export interface StatusPayload {
  id: string;
  status: JobStatus;
  source_type: "upload" | "youtube";
  source: string;
  stage: string | null;
  stage_label: string | null;
  stage_progress: number;
  progress: number;
  message: string | null;
  error: { code: string; message: string } | null;
  stages: StageState[];
  title: string | null;
  created_at: string | null;
  completed_at: string | null;
  stems?: { status: string; progress: number; message: string | null };
}

export interface AnalysisPayload extends StatusPayload {
  metadata: Partial<Metadata> | null;
  results: AnalysisResults | null;
  audio: { available: boolean; expires_at: string | null; url: string | null };
  stems: { status: string; progress: number; message: string | null; results: StemsResults | null };
  explanations: Record<string, string>;
}

export interface Health {
  status: string;
  engine_version: string;
  capabilities: {
    ffmpeg: boolean;
    ffprobe: boolean;
    youtube: boolean;
    stems: boolean;
    stems_reason: string | null;
    llm: boolean;
    llm_audiences: string[];
  };
  limits: { max_upload_mb: number; max_duration_seconds: number; audio_retention_minutes: number; formats: string[] };
}

export interface RecentItem extends StatusPayload {
  overview: Partial<AnalysisResults["overview"]>;
  artist: string | null;
}
