"use client";

// Data hook for the progress dashboard. Fetches the overview + vocabulary
// growth series for the authenticated user and exposes loading/error state.

import { useCallback, useEffect, useState } from "react";
import { api, ProgressOverview, VocabPoint } from "./api";

export interface ProgressData {
  overview: ProgressOverview | null;
  growth: VocabPoint[];
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export function useProgress(
  token: string | null,
  language?: string,
): ProgressData {
  const [overview, setOverview] = useState<ProgressOverview | null>(null);
  const [growth, setGrowth] = useState<VocabPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const [ov, gr] = await Promise.all([
        api.progressOverview(token, language),
        api.vocabularyGrowth(token, language),
      ]);
      setOverview(ov);
      setGrowth(gr);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load progress");
    } finally {
      setLoading(false);
    }
  }, [token, language]);

  useEffect(() => {
    void load();
  }, [load]);

  return { overview, growth, loading, error, reload: () => void load() };
}
